# AI-assisted
"""A7 ML 建模器（P2a 计划 §Task 12.3 / docs/03 §3.3 A7、§6 ML 数据不足策略）。

run_ml(req: MLRequest) -> MLResponse：
- data_ref 组装数据：只读 SELECT（sqlguard 白名单校验 + 只读账号执行，红线 R1）或 CSV 路径；
- 数据前置校验（docs/03 §6 阈值：样本 ≥ 30、特征非全常数、target 缺失值不过半），
  失败抛 MLDataError（message 用户可读）；
- decision_tree/random_forest 依目标列形态自动判别 task_type（regression/classification），
  无监督模型（kmeans/isolation_forest）忽略 target 并记 warning；
- 模板代码注入 A6 沙箱执行（templates.render_ml_template + runner.run_python），
  模型 joblib 在沙箱工作目录生成、经 copy_out 收走后落到 models/<task_id>.joblib
  （目录已 gitignore；沙箱内不写持久路径，红线 R2）；
- 结果解析为 MLResponse；explanation 由指标与特征重要性确定性拼装（不依赖 LLM）。

prepare_ml / run_ml 拆分：pipeline 需要"先看代码再执行"（code_generated 事件在
训练评估步骤之前发出），故准备（取数/校验/渲染）与执行可分两步，也可 run_ml 一步完成。
"""
from __future__ import annotations

import logging
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import Settings, get_settings
from app.ml.contracts import FeatureImportance, MLPlot, MLRequest, MLResponse
from app.ml.templates import render_ml_template
from app.sandbox.runner import run_python
from app.sqlguard.executor import SQLExecutionError, execute_readonly
from app.sqlguard.validator import SQLValidationError, validate_sql

logger = logging.getLogger("a07.ml")

_AGENT_DIR = Path(__file__).resolve().parents[2]   # app/ml/modeler.py -> a07-agent
MODELS_DIR = _AGENT_DIR / "models"      # 默认模型持久化目录（.gitignore 已含 a07-agent/models/）
DEFAULT_TIMEOUT_S = 90.0                # ML 训练比纯 pandas 慢，沙箱超时放宽
ML_SANDBOX_MEMORY_MB = 2048             # sklearn 全栈 import 提交内存 ~1.4GB（实测），默认 1024MB 必炸
SAMPLE_MIN_ROWS = 30                    # docs/03 §6：样本量阈值
TARGET_MISSING_MAX = 0.5                # 目标列缺失值占比上限
CAT_MAX_CARDINALITY = 50                # 高基数类别列剔除阈值（与模板一致）
PREDICTION_SAMPLE_MAX = 50              # MLResponse.predictions_sample 行数上限

# 允许透传给模板的超参（键 → (类型, 下界, 上界)）；越界收敛、其余键剔除，杜绝参数注入
PARAM_SPEC: dict[str, tuple[type, float, float]] = {
    "n_clusters": (int, 2, 10),
    "contamination": (float, 0.01, 0.5),
    "n_estimators": (int, 10, 200),
    "max_depth": (int, 2, 20),
    "test_size": (float, 0.1, 0.5),
}

# 各模型实际消费的参数键（消费了才不告警）
_PARAM_CONSUMERS: dict[str, set[str]] = {
    "linear_regression": set(),
    "logistic_regression": set(),
    "decision_tree": {"max_depth", "test_size"},
    "random_forest": {"n_estimators", "max_depth", "test_size"},
    "kmeans": {"n_clusters"},
    "isolation_forest": {"contamination"},
}


class MLDataError(ValueError):
    """建模数据/执行失败（message 用户可读；pipeline 据此降级、REST 据此回 400）。"""


@dataclass
class MLPrepared:
    """prepare_ml 的产物：渲染好的沙箱代码 + 输入 CSV + 任务元信息。"""

    task_id: str
    code: str
    task_type: str
    params: dict[str, Any]
    df: pd.DataFrame
    csv_path: Path
    csv_dir: Path
    warnings: list[str] = field(default_factory=list)


# ---- 数据加载与前置校验 ----


def _load_frame(data_ref: str, cfg: Settings) -> tuple[pd.DataFrame, str | None]:
    """data_ref → DataFrame；返回 (df, 校验后的 SQL 或 None)。"""
    text = (data_ref or "").strip()
    if not text:
        raise MLDataError("data_ref 为空：请提供只读 SELECT SQL 或 SQL 结果 CSV 路径")
    lowered = text.lower()
    if lowered.startswith("select") or lowered.startswith("with"):
        try:
            validated = validate_sql(text, dialect="mysql", max_limit=cfg.sql_max_limit)
        except SQLValidationError as exc:
            raise MLDataError(f"data_ref 必须是单条只读 SELECT 语句：{exc}") from exc
        try:
            result = execute_readonly(validated, cfg)
        except SQLExecutionError as exc:
            raise MLDataError(f"建模取数失败：{exc}") from exc
        return pd.DataFrame(result.rows, columns=result.columns), validated
    path = Path(text)
    if not path.is_file():
        raise MLDataError(f"data_ref 既不是只读 SELECT 语句，也不是可用的 CSV 文件：{text}")
    try:
        return pd.read_csv(path), None
    except (OSError, ValueError) as exc:
        raise MLDataError(f"CSV 读取失败：{exc}") from exc


def _looks_like_datetime(s: pd.Series) -> bool:
    """目标列是否为日期/时间（含 ISO 日期字符串）；用于禁止把时间戳当分类标签。"""
    s = s.dropna()
    if s.empty:
        return False
    if pd.api.types.is_datetime64_any_dtype(s) or pd.api.types.is_timedelta64_dtype(s):
        return True
    if pd.api.types.is_numeric_dtype(s):
        return False
    sample = s.astype(str).head(80)
    if sample.str.match(r"^\d{4}-\d{2}-\d{2}([ T].*)?$").mean() >= 0.8:
        return True
    if sample.str.match(r"^\d{4}/\d{2}/\d{2}").mean() >= 0.8:
        return True
    try:
        parsed = pd.to_datetime(s.head(80), errors="coerce")
        return float(parsed.notna().mean()) >= 0.8 and sample.str.len().between(6, 32).mean() >= 0.8
    except (ValueError, TypeError):
        return False


def resolve_task_type(model_type: str, target: pd.Series | None) -> str:
    """解析任务类型：决策树/随机森林依目标列形态自动判别（类别/少取值→分类）。

    硬约束（BUG-031）：日期/时间不得作分类标签；分类目标 unique 必须 ≥2，
    否则抛 MLDataError（禁止“单类仍训练成功”）。
    """
    if model_type == "kmeans":
        return "clustering"
    if model_type == "isolation_forest":
        return "anomaly"
    # 监督学习（含 linear/logistic/tree/forest）一律拒绝日期目标（BUG-031）
    if target is not None and not target.dropna().empty and _looks_like_datetime(target.dropna()):
        raise MLDataError(
            f"目标列含日期/时间取值，不能作为监督学习目标（请改选数值列如 qualified_qty/defect_qty，"
            "或使用聚类/异常检测等无监督算法）"
        )
    if model_type == "linear_regression":
        return "regression"
    if model_type == "logistic_regression":
        return "classification"
    if target is None or target.dropna().empty:
        return "regression"
    s = target.dropna()
    numeric_ratio = float(pd.to_numeric(s, errors="coerce").notna().mean())
    if numeric_ratio < 0.5:
        # 非数值 → 分类；要求可分
        n = int(s.nunique())
        if n < 2:
            raise MLDataError(
                f"目标列仅有 {n} 个类别，无法训练分类模型；请更换有区分度的目标列"
            )
        return "classification"
    n = int(s.nunique())
    if n <= 10:
        if n < 2:
            raise MLDataError(
                f"目标列仅有 {n} 个取值，无法作为分类目标；请更换目标列"
            )
        return "classification"
    return "regression"


def _constant_features(df: pd.DataFrame, features: list[str]) -> list[str]:
    """找出取值恒定不变的特征列（数值按 to_numeric 口径、类别按字符串口径）。"""
    const: list[str] = []
    for col in features:
        numeric = pd.to_numeric(df[col], errors="coerce")
        if numeric.notna().mean() >= 0.5:
            if numeric.nunique(dropna=True) <= 1:
                const.append(col)
        elif df[col].astype(str).nunique(dropna=False) <= 1:
            const.append(col)
    return const


def _validate_frame(df: pd.DataFrame, req: MLRequest, task_type: str) -> None:
    """前置校验：列存在 / 样本量 / 目标缺失 / 特征全常数（docs/03 §6，可读错误）。"""
    missing = [c for c in req.features if c not in df.columns]
    if req.target and req.target not in df.columns:
        missing.append(req.target)
    if missing:
        raise MLDataError(
            f"建模数据缺少列：{missing}；当前数据列为 {list(df.columns)}，请核对特征/目标列名"
        )
    if len(df) < SAMPLE_MIN_ROWS:
        raise MLDataError(
            f"建模样本量不足（{len(df)} 行 < {SAMPLE_MIN_ROWS}），"
            "请放宽查询时间或筛选条件获取更多数据后重试"
        )
    if req.target and task_type in ("regression", "classification"):
        if task_type == "regression":
            valid = pd.to_numeric(df[req.target], errors="coerce")
        else:
            valid = df[req.target]
            n_classes = int(valid.dropna().nunique())
            if n_classes < 2:
                raise MLDataError(
                    f"目标列 {req.target} 仅有 {n_classes} 个类别，无法训练分类模型；"
                    "请更换有区分度的目标列（如按数值阈值构造标签）"
                )
        missing_ratio = 1.0 - float(valid.notna().mean())
        if missing_ratio > TARGET_MISSING_MAX:
            raise MLDataError(
                f"目标列 {req.target} 缺失值过多（有效值仅 {valid.notna().sum()}/{len(df)}），"
                "请更换目标列或先清洗数据"
            )
    const = _constant_features(df, req.features)
    if len(const) == len(req.features):
        raise MLDataError(f"所有特征列均为常数列（{const}），无信息量可用于建模；请更换特征列")


def sanitize_ml_parameters(model_type: str, parameters: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    """参数消毒：白名单键 + 类型收敛 + 越界钳制 + 未消费键告警（杜绝经参数的代码注入）。"""
    cleaned: dict[str, Any] = {}
    warnings: list[str] = []
    consumers = _PARAM_CONSUMERS.get(model_type, set())
    for key, value in (parameters or {}).items():
        if key not in PARAM_SPEC:
            warnings.append(f"已忽略不支持的建模参数：{key}")
            continue
        typ, low, high = PARAM_SPEC[key]
        try:
            if typ is int:
                num = int(float(value))
            else:
                num = float(value)
        except (TypeError, ValueError):
            warnings.append(f"建模参数 {key} 取值非法（{value!r}），已忽略")
            continue
        if num < low or num > high:
            num = min(max(num, low), high)
            warnings.append(f"建模参数 {key} 越界，已收敛到 {num}")
        if key not in consumers:
            warnings.append(f"参数 {key} 对模型 {model_type} 无效，已忽略")
            continue
        cleaned[key] = num
    return cleaned, warnings


# ---- 准备与执行 ----


def prepare_ml(req: MLRequest, cfg: Settings | None = None) -> MLPrepared:
    """加载 data_ref → 前置校验 → 参数消毒 → 渲染沙箱代码并写好输入 CSV。"""
    cfg = cfg or get_settings()
    df, _sql = _load_frame(req.data_ref, cfg)
    target_series = df[req.target] if (req.target and req.target in df.columns) else None
    task_type = resolve_task_type(req.model_type, target_series)
    warnings: list[str] = []
    if req.target and task_type in ("clustering", "anomaly"):
        warnings.append(
            f"无监督模型 {req.model_type} 不使用 target，已忽略目标列 {req.target}"
        )
    _validate_frame(df, req, task_type)
    params, param_warnings = sanitize_ml_parameters(req.model_type, req.parameters)
    warnings.extend(param_warnings)

    code = render_ml_template(req.model_type, task_type, req.features, req.target, params)
    task_id = f"ml_{time.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
    csv_dir = Path(_AGENT_DIR) / "logs" / "ml_input" / task_id
    csv_dir.mkdir(parents=True, exist_ok=True)
    csv_path = csv_dir / "input.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8")
    logger.info(
        "ml_prepared task_id=%s model_type=%s task_type=%s rows=%d features=%s",
        task_id, req.model_type, task_type, len(df), req.features,
    )
    return MLPrepared(
        task_id=task_id,
        code=code,
        task_type=task_type,
        params=params,
        df=df,
        csv_path=csv_path,
        csv_dir=csv_dir,
        warnings=warnings,
    )


def _model_path_text(dest: Path) -> str:
    """模型路径对外展示：引擎目录内用相对路径（models/<task_id>.joblib），否则绝对路径。"""
    try:
        return dest.relative_to(_AGENT_DIR).as_posix()
    except ValueError:
        return str(dest)


def _execute_prepared(req: MLRequest, prepared: MLPrepared, timeout_s: float, models_dir: Path) -> MLResponse:
    """渲染产物送沙箱执行 → 解析 result → MLResponse（含模型持久化与解释拼装）。"""
    warnings = list(prepared.warnings)
    models_dir.mkdir(parents=True, exist_ok=True)
    dest = models_dir / f"{prepared.task_id}.joblib"
    res = run_python(
        prepared.code,
        str(prepared.csv_path),
        timeout_s=timeout_s,
        copy_out={"model.joblib": str(dest)},
        memory_mb=ML_SANDBOX_MEMORY_MB,
    )
    warnings.extend(res.warnings)
    if not res.ok:
        raise MLDataError(f"建模沙箱执行失败：{res.error or '未知原因'}")
    stats = res.stats
    error = stats.get("error")
    if isinstance(error, str) and error.strip():
        raise MLDataError(f"建模失败：{error}")
    metrics = stats.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        raise MLDataError("建模结果异常：未产出评估指标（沙箱模板协议被破坏）")

    dropped = stats.get("dropped_features")
    if isinstance(dropped, list) and dropped:
        warnings.append(f"已剔除常数/高基数特征列：{dropped}（不参与建模）")

    raw_importance = stats.get("feature_importance")
    importance = [
        FeatureImportance(name=str(item.get("name", "")), score=float(item.get("score", 0.0)))
        for item in (raw_importance or [])
        if isinstance(item, dict)
    ]
    raw_plots = stats.get("plots")
    plots = [
        MLPlot(type=str(item.get("type", "")), data=item.get("data") or {})
        for item in (raw_plots or [])
        if isinstance(item, dict)
    ]
    sample = stats.get("predictions_sample")
    predictions = [row for row in (sample if isinstance(sample, list) else []) if isinstance(row, dict)]
    predictions = predictions[:PREDICTION_SAMPLE_MAX]

    model_path: str | None = None
    if dest.is_file() and dest.stat().st_size > 0:
        model_path = _model_path_text(dest)
    else:
        warnings.append("模型文件未能持久化（沙箱未产出 model.joblib），model_path 为空")

    explanation = _compose_explanation(prepared.task_type, metrics, importance, predictions)
    resp = MLResponse(
        task_id=prepared.task_id,
        model_type=req.model_type,
        task_type=prepared.task_type,  # type: ignore[arg-type]
        metrics=metrics,
        feature_importance=importance,
        plots=plots,
        predictions_sample=predictions,
        explanation=explanation,
        model_path=model_path,
        warnings=warnings,
    )
    logger.info(
        "ml_done task_id=%s model_type=%s ok=%s model_path=%s",
        prepared.task_id, req.model_type, bool(model_path), model_path,
    )
    return resp


def run_ml(
    req: MLRequest,
    *,
    timeout_s: float | None = None,
    models_dir: str | Path | None = None,
    cfg: Settings | None = None,
    prepared: MLPrepared | None = None,
) -> MLResponse:
    """执行一次建模任务（契约见模块文档）。

    prepared 传None 时内部完成准备并自清理临时 CSV；外部传入 prepared（pipeline 先发
    code_generated 事件的场景）时临时目录由调用方清理。
    """
    timeout = float(timeout_s) if timeout_s and float(timeout_s) > 0 else DEFAULT_TIMEOUT_S
    mdir = Path(models_dir) if models_dir else MODELS_DIR
    if prepared is None:
        prepared = prepare_ml(req, cfg)
        try:
            return _execute_prepared(req, prepared, timeout, mdir)
        finally:
            shutil.rmtree(prepared.csv_dir, ignore_errors=True)
    return _execute_prepared(req, prepared, timeout, mdir)


# ---- 结果加工 ----


def _top_sample_label(sample: list[dict[str, Any]]) -> str:
    """从样本首行取一个可读标识（首个字符串型业务列，跳过结果注入列）。"""
    skip = {"anomaly_score", "is_anomaly", "cluster", "y_true", "y_pred"}
    for row in sample[:1]:
        for key, value in row.items():
            if key in skip:
                continue
            if isinstance(value, str) and value.strip():
                return f"{key}={value}"
    return ""


def _compose_explanation(
    task_type: str,
    metrics: dict[str, Any],
    importance: list[FeatureImportance],
    sample: list[dict[str, Any]],
) -> str:
    """由指标与特征重要性确定性拼装中文解释（不依赖 LLM，数字全部可溯源）。"""
    top = f"对结果影响最大的特征是「{importance[0].name}」（重要性 {importance[0].score:.3f}）。" if importance else ""
    if task_type == "regression":
        text = (
            f"模型在测试集（{metrics.get('test_rows', '?')} 行）上 "
            f"R²={metrics.get('r2', 0):.3f}、MAE={metrics.get('mae', 0):.3f}、RMSE={metrics.get('rmse', 0):.3f}。"
        )
    elif task_type == "classification":
        text = (
            f"模型在测试集（{metrics.get('test_rows', '?')} 行）上准确率 {metrics.get('accuracy', 0):.3f}、"
            f"宏平均 F1 {metrics.get('f1', 0):.3f}。"
        )
    elif task_type == "clustering":
        sizes = metrics.get("cluster_sizes") or {}
        size_text = "、".join(f"簇{k}：{v}条" for k, v in list(sizes.items())[:6])
        text = (
            f"聚类得到 {metrics.get('n_clusters', '?')} 个簇，轮廓系数 {metrics.get('silhouette', 0):.3f}"
            f"（{size_text}）。"
        )
    else:
        label = _top_sample_label(sample)
        text = (
            f"共检出 {metrics.get('n_anomalies', 0)} 条异常记录"
            f"（占比 {metrics.get('anomaly_ratio', 0):.1%}），异常分数阈值为 {metrics.get('threshold', 0):.4f}。"
        )
        if label:
            text += f"最异常样本：{label}。"
    return text + (f" {top}" if top else " 无监督模型未计算特征重要性。" if task_type in ("clustering", "anomaly") and not importance else "")


def ml_payload(resp: MLResponse) -> dict[str, Any]:
    """ml_result 事件 / REST 响应载荷：MLResponse.model_dump + camelCase 补充（docs/03 §4）。"""
    data = resp.model_dump()
    data.update(
        {
            "taskId": resp.task_id,
            "modelType": resp.model_type,
            "taskType": resp.task_type,
            "featureImportance": [fi.model_dump() for fi in resp.feature_importance],
            "predictionsSample": resp.predictions_sample,
            "modelPath": resp.model_path,
        }
    )
    return data
