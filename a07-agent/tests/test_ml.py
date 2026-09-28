# AI-assisted
"""T-012 A7 ML 建模器测试（P2a 计划 §Task 12，先于实现编写——严格 TDD）。

覆盖面：
- contracts：MLRequest/MLResponse pydantic 契约（model_type 六值枚举、字段齐全）
- templates：六算法沙箱代码模板渲染（统一特征工程/固定切分/参数消毒）
- modeler.run_ml：六算法各一个真实小样本沙箱用例（评估指标/图数据/特征重要性/样本表）
- 数据前置校验：样本<30、列不存在、target 缺失值过多、特征全常数 → 可读错误
- joblib 持久化：模型落到 models_dir，model_path 可定位
- data_ref 两种形态：CSV 路径 / 只读 SQL（经 validate_sql + execute_readonly）
- pipeline execution_mode="ml" 分支（mock LLM + 真沙箱）：
  code_generated → ml_result（camelCase 载荷）→ 异常样本 table → done
- 工具注册表 run_ml_model；内部 REST POST /api/agent/ml/run
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.retriever import DEFAULT_CORPUS_PATH, Retriever
from app.sandbox.runner import run_python
from app.sqlguard.executor import ExecResult

# ---- 合成数据 fixtures（小型、可复现，np.seed 固定）----


def _regression_df(n: int = 80) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    f1 = rng.normal(10, 2, n)
    f2 = rng.normal(5, 1, n)
    cat = rng.choice(["A", "B"], n)
    y = 3 * f1 + 2 * f2 + np.where(cat == "A", 5.0, 0.0) + rng.normal(0, 0.5, n)
    return pd.DataFrame({"f1": f1.round(2), "f2": f2.round(2), "cat": cat, "y": y.round(2)})


def _classification_df(n: int = 80) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    f1 = rng.normal(0, 1, n)
    f2 = rng.normal(0, 1, n)
    cat = rng.choice(["甲", "乙", "丙"], n)
    label = ((f1 + 0.8 * f2 + np.where(cat == "甲", 1.0, 0.0)) > 0.3).astype(int)
    return pd.DataFrame({"f1": f1.round(3), "f2": f2.round(3), "cat": cat, "label": label})


def _cluster_df(n: int = 90) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    centers = np.array([[0, 0], [8, 8], [0, 8]], dtype=float)
    idx = rng.integers(0, 3, n)
    pts = centers[idx] + rng.normal(0, 0.6, (n, 2))
    return pd.DataFrame({"x1": pts[:, 0].round(3), "x2": pts[:, 1].round(3)})


def _anomaly_df(n_normal: int = 55, n_outlier: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(13)
    x1 = rng.normal(0, 1, n_normal).tolist() + [20 + i for i in range(n_outlier)]
    x2 = rng.normal(5, 1, n_normal).tolist() + [50 + i for i in range(n_outlier)]
    return pd.DataFrame({"x1": np.round(x1, 3), "x2": np.round(x2, 3)})


def _equipment_df(n: int = 60, n_outlier: int = 6) -> pd.DataFrame:
    """EQ-07 风格设备停机明细：多数正常停机 + 少量异常长停机/高频报警。"""
    rng = np.random.default_rng(21)
    rows = []
    for i in range(n - n_outlier):
        rows.append(
            {
                "equipment_name": f"EQ-{rng.integers(1, 11):02d}",
                "production_line": f"L{rng.integers(1, 4)}",
                "downtime_minutes": int(max(5, rng.normal(45, 15))),
                "alarm_count": int(max(0, rng.normal(2, 1))),
                "reason": str(rng.choice(["故障", "换型", "保养", "待料"])),
            }
        )
    for i in range(n_outlier):
        rows.append(
            {
                "equipment_name": f"EQ-{rng.integers(1, 11):02d}",
                "production_line": f"L{rng.integers(1, 4)}",
                "downtime_minutes": int(rng.integers(300, 600)),
                "alarm_count": int(rng.integers(15, 40)),
                "reason": "故障",
            }
        )
    return pd.DataFrame(rows)


def _write_csv(tmp_path: Path, df: pd.DataFrame, name: str) -> str:
    p = tmp_path / name
    df.to_csv(p, index=False, encoding="utf-8")
    return str(p)


@pytest.fixture(scope="module")
def regression_csv(tmp_path_factory: pytest.TempPathFactory) -> str:
    return _write_csv(tmp_path_factory.mktemp("mlreg"), _regression_df(), "reg.csv")


@pytest.fixture(scope="module")
def classification_csv(tmp_path_factory: pytest.TempPathFactory) -> str:
    return _write_csv(tmp_path_factory.mktemp("mlcls"), _classification_df(), "cls.csv")


@pytest.fixture(scope="module")
def cluster_csv(tmp_path_factory: pytest.TempPathFactory) -> str:
    return _write_csv(tmp_path_factory.mktemp("mlclu"), _cluster_df(), "clu.csv")


@pytest.fixture(scope="module")
def anomaly_csv(tmp_path_factory: pytest.TempPathFactory) -> str:
    return _write_csv(tmp_path_factory.mktemp("mlano"), _anomaly_df(), "ano.csv")


@pytest.fixture(scope="module")
def equipment_csv(tmp_path_factory: pytest.TempPathFactory) -> str:
    return _write_csv(tmp_path_factory.mktemp("mleq"), _equipment_df(), "eq.csv")


@pytest.fixture
def models_dir(tmp_path: Path) -> Path:
    d = tmp_path / "models"
    d.mkdir()
    return d


def _req(model_type: str, data_ref: str, features: list[str], target: str | None = None, **kw: Any):
    from app.ml.contracts import MLRequest

    return MLRequest(model_type=model_type, features=features, target=target, data_ref=data_ref, **kw)


def _run_ml(req, **kw):
    from app.ml.modeler import run_ml

    return run_ml(req, **kw)


# ---- contracts（§Task 12.1）----


class TestMLContracts:
    def test_request_accepts_six_model_types(self, equipment_csv):
        from app.ml.contracts import MLRequest

        for mt in (
            "linear_regression",
            "decision_tree",
            "random_forest",
            "logistic_regression",
            "kmeans",
            "isolation_forest",
        ):
            req = MLRequest(model_type=mt, features=["downtime_minutes"], data_ref=equipment_csv)
            assert req.model_type == mt
            assert req.parameters == {}

    def test_request_rejects_unknown_model_type(self, equipment_csv):
        from pydantic import ValidationError

        from app.ml.contracts import MLRequest

        with pytest.raises(ValidationError):
            MLRequest(model_type="svm", features=["x"], data_ref=equipment_csv)

    def test_request_rejects_empty_features(self, equipment_csv):
        from pydantic import ValidationError

        from app.ml.contracts import MLRequest

        with pytest.raises(ValidationError):
            MLRequest(model_type="kmeans", features=[], data_ref=equipment_csv)

    def test_response_fields_complete(self):
        from app.ml.contracts import MLResponse

        resp = MLResponse(
            task_id="ml_t1",
            model_type="random_forest",
            task_type="regression",
            metrics={"r2": 0.9},
            feature_importance=[{"name": "f1", "score": 0.8}],
            plots=[{"type": "scatter", "data": {"points": []}}],
            predictions_sample=[{"y_true": 1, "y_pred": 1.1}],
            explanation="解释",
            model_path=None,
        )
        dump = resp.model_dump()
        for key in (
            "metrics",
            "feature_importance",
            "plots",
            "predictions_sample",
            "explanation",
            "model_path",
        ):
            assert key in dump
        assert dump["feature_importance"][0]["name"] == "f1"


# ---- templates（§Task 12.2）----


class TestMLTemplates:
    def test_render_contains_feature_engineering_and_fixed_split(self):
        from app.ml.templates import render_ml_template

        code = render_ml_template(
            "random_forest", "regression", ["f1", "f2"], "y", {"n_estimators": 50}
        )
        assert "train_test_split" in code
        assert "0.25" in code
        assert "random_state=42" in code
        assert "RandomForestRegressor" in code
        assert "median" in code  # 数值列中位数填充
        assert "get_dummies" in code  # 类别列 one-hot

    def test_render_per_model_type(self):
        from app.ml.templates import render_ml_template

        cases = {
            "linear_regression": "LinearRegression",
            "decision_tree": "DecisionTree",
            "random_forest": "RandomForest",
            "logistic_regression": "LogisticRegression",
            "kmeans": "KMeans",
            "isolation_forest": "IsolationForest",
        }
        for mt, cls in cases.items():
            code = render_ml_template(mt, "regression", ["f1"], "y", {})
            assert cls in code, f"{mt} 模板应包含 {cls}"

    def test_render_rejects_unknown_type(self):
        from app.ml.templates import render_ml_template

        with pytest.raises(ValueError):
            render_ml_template("svm", "regression", ["f1"], "y", {})

    def test_render_parameters_injected_sanitized(self):
        from app.ml.templates import render_ml_template

        code = render_ml_template(
            "isolation_forest", "anomaly", ["x1", "x2"], None, {"contamination": 0.2}
        )
        assert "0.2" in code

    def test_sandbox_template_runs_end_to_end(self, classification_csv):
        """模板渲染产物本身可在沙箱内直接执行并产出契约结果键。"""
        from app.ml.modeler import ML_SANDBOX_MEMORY_MB
        from app.ml.templates import render_ml_template

        code = render_ml_template(
            "decision_tree", "classification", ["f1", "f2", "cat"], "label", {}
        )
        res = run_python(
            code, classification_csv, timeout_s=90, memory_mb=ML_SANDBOX_MEMORY_MB
        )
        assert res.ok, res.error
        assert "error" not in res.stats, res.stats.get("error")
        assert isinstance(res.stats["metrics"], dict)
        assert res.stats["metrics"]["accuracy"] > 0.6
        assert res.stats["feature_importance"]
        assert res.stats["plots"]


# ---- modeler.run_ml 六算法真实小样本用例（§Task 12.3/12.5）----


class TestRunMLAlgorithms:
    def test_linear_regression(self, regression_csv):
        resp = _run_ml(_req("linear_regression", regression_csv, ["f1", "f2", "cat"], "y"))
        assert resp.task_type == "regression"
        assert resp.metrics["r2"] > 0.9
        assert 0 <= resp.metrics["mae"] < 2
        assert resp.metrics["rmse"] > 0
        # 预测散点图数据
        scatter = [p for p in resp.plots if p.type == "scatter"]
        assert scatter and len(scatter[0].data["points"]) > 10
        # 非树模型 → permutation_importance
        assert resp.feature_importance, "线性回归应有置换重要性"
        names = {fi.name for fi in resp.feature_importance}
        assert {"f1", "f2"} <= names
        assert resp.explanation
        assert resp.predictions_sample

    def test_decision_tree_classification(self, classification_csv):
        resp = _run_ml(_req("decision_tree", classification_csv, ["f1", "f2", "cat"], "label"))
        assert resp.task_type == "classification"
        assert resp.metrics["accuracy"] > 0.7
        for key in ("precision", "recall", "f1"):
            assert key in resp.metrics
        # 树模型 → feature_importances_
        assert resp.feature_importance and {fi.name for fi in resp.feature_importance} == {"f1", "f2", "cat"}
        heat = [p for p in resp.plots if p.type == "heatmap"]
        assert heat and heat[0].data["matrix"]
        assert resp.predictions_sample and "y_pred" in resp.predictions_sample[0]

    def test_random_forest_regression(self, regression_csv):
        resp = _run_ml(_req("random_forest", regression_csv, ["f1", "f2", "cat"], "y"))
        assert resp.task_type == "regression"
        assert resp.metrics["r2"] > 0.85
        assert resp.feature_importance, "随机森林应有特征重要性"
        top = resp.feature_importance[0]
        assert top.name in ("f1", "f2") and top.score > 0.2

    def test_logistic_regression(self, classification_csv):
        resp = _run_ml(_req("logistic_regression", classification_csv, ["f1", "f2", "cat"], "label"))
        assert resp.task_type == "classification"
        assert resp.metrics["accuracy"] > 0.7
        # 二分类 → ROC 点
        roc = [p for p in resp.plots if p.type == "line" and p.data.get("y") == "tpr"]
        assert roc and len(roc[0].data["points"]) > 2 and "auc" in roc[0].data

    def test_kmeans_clustering(self, cluster_csv):
        resp = _run_ml(_req("kmeans", cluster_csv, ["x1", "x2"], None, parameters={"n_clusters": 3}))
        assert resp.task_type == "clustering"
        assert resp.metrics["silhouette"] > 0.5
        assert resp.metrics["n_clusters"] == 3
        pca = [p for p in resp.plots if p.type == "scatter" and "series" in p.data]
        assert pca and len(pca[0].data["series"]) == 3
        assert resp.predictions_sample and "cluster" in resp.predictions_sample[0]

    def test_isolation_forest_equipment_style(self, equipment_csv):
        """§Task 12.5：IsolationForest 用 EQ-07 风格停机数据，异常分数+top 异常行。"""
        resp = _run_ml(_req("isolation_forest", equipment_csv, ["downtime_minutes", "alarm_count"], None))
        assert resp.task_type == "anomaly"
        assert resp.metrics["n_anomalies"] >= 1
        assert 0 <= resp.metrics["anomaly_ratio"] <= 0.5
        assert "threshold" in resp.metrics
        sample = resp.predictions_sample
        assert sample and "anomaly_score" in sample[0] and "is_anomaly" in sample[0]
        scores = [r["anomaly_score"] for r in sample]
        assert scores == sorted(scores, reverse=True), "异常样本应按分数降序"
        # 分布图带阈值线
        hist = [p for p in resp.plots if p.type == "histogram"]
        assert hist and "threshold" in hist[0].data
        # 异常行应携带原始列（设备名可读）
        assert "equipment_name" in sample[0]

    def test_unsupervised_target_ignored_with_warning(self, equipment_csv):
        resp = _run_ml(_req("isolation_forest", equipment_csv, ["downtime_minutes"], "reason"))
        assert resp.task_type == "anomaly"
        assert any("target" in w for w in resp.warnings), resp.warnings


# ---- 数据前置校验（docs/03 §6：可读错误）----


class TestMLValidation:
    def test_too_few_samples_readable_error(self, tmp_path: Path):
        csv = _write_csv(tmp_path, _regression_df(10), "small.csv")
        with pytest.raises(ValueError) as ei:
            _run_ml(_req("linear_regression", csv, ["f1", "f2"], "y"))
        assert "样本" in str(ei.value)

    def test_missing_feature_column_readable(self, regression_csv):
        with pytest.raises(ValueError) as ei:
            _run_ml(_req("linear_regression", regression_csv, ["f1", "nope"], "y"))
        assert "nope" in str(ei.value)

    def test_missing_target_column_readable(self, regression_csv):
        with pytest.raises(ValueError) as ei:
            _run_ml(_req("linear_regression", regression_csv, ["f1", "f2"], "nope"))
        assert "nope" in str(ei.value)

    def test_target_too_many_missing_readable(self, tmp_path: Path):
        df = _regression_df(60)
        df.loc[df.index[:40], "y"] = np.nan
        csv = _write_csv(tmp_path, df, "nan_target.csv")
        with pytest.raises(ValueError) as ei:
            _run_ml(_req("linear_regression", csv, ["f1", "f2"], "y"))
        assert "缺失" in str(ei.value)

    def test_all_constant_features_readable(self, tmp_path: Path):
        df = _regression_df(60)
        df["c1"] = 1.0
        df["c2"] = "same"
        csv = _write_csv(tmp_path, df, "const.csv")
        with pytest.raises(ValueError) as ei:
            _run_ml(_req("linear_regression", csv, ["c1", "c2"], "y"))
        assert "常数" in str(ei.value)

    def test_data_ref_neither_sql_nor_file(self):
        with pytest.raises(ValueError):
            _run_ml(_req("kmeans", "not-a-file-nor-sql", ["x1"]))

    def test_datetime_target_rejected_for_classification(self, tmp_path: Path):
        """BUG-031：日期目标不得当分类标签（禁止单类“训练成功”）。"""
        df = _classification_df(60)
        df["d"] = "2026-06-21"
        csv = _write_csv(tmp_path, df, "date_target.csv")
        with pytest.raises(ValueError) as ei:
            _run_ml(_req("random_forest", csv, ["f1", "f2"], "d"))
        msg = str(ei.value)
        assert "日期" in msg or "时间" in msg

    def test_single_class_target_rejected(self, tmp_path: Path):
        """BUG-031：分类目标仅 1 类 → 可读错误。"""
        df = _classification_df(60)
        df["label"] = "2026-06-21" if False else 1  # 单类
        csv = _write_csv(tmp_path, df, "one_class.csv")
        with pytest.raises(ValueError) as ei:
            _run_ml(_req("decision_tree", csv, ["f1", "f2"], "label"))
        assert "类别" in str(ei.value) or "取值" in str(ei.value)


# ---- joblib 持久化 + data_ref=SQL ----


class TestMLPersistence:
    def test_model_saved_to_models_dir(self, regression_csv, models_dir: Path):
        resp = _run_ml(
            _req("random_forest", regression_csv, ["f1", "f2", "cat"], "y"), models_dir=models_dir
        )
        assert resp.model_path
        saved = models_dir / Path(resp.model_path).name
        assert saved.exists() and saved.stat().st_size > 0
        import joblib

        bundle = joblib.load(saved)
        assert hasattr(bundle["model"], "predict"), "bundle 应含可推理的模型对象"
        assert bundle["feature_cols"] and bundle["model_type"] == "random_forest"

    def test_data_ref_as_sql_uses_readonly_chain(self, monkeypatch, tmp_path: Path):
        from app.ml import modeler as ml_modeler

        df = _regression_df(60)
        captured: dict[str, Any] = {}

        def _fake_exec(sql, cfg, **kw):
            captured["sql"] = sql
            return ExecResult(
                columns=list(df.columns),
                rows=df.to_dict("records"),
                rowcount=len(df),
                elapsed_ms=1.0,
                truncated=False,
            )

        monkeypatch.setattr(ml_modeler, "execute_readonly", _fake_exec)
        resp = _run_ml(
            _req("random_forest", "SELECT f1, f2, cat, y FROM demo_tbl", ["f1", "f2", "cat"], "y"),
            models_dir=tmp_path / "m2",
        )
        assert resp.metrics["r2"] > 0.8
        assert "demo_tbl" in captured["sql"]

    def test_data_ref_sql_rejected_non_select(self, monkeypatch):
        from app.ml.modeler import run_ml
        from app.ml.contracts import MLRequest

        with pytest.raises(ValueError) as ei:
            run_ml(MLRequest(model_type="kmeans", features=["x1"], data_ref="DELETE FROM t"))
        assert "只读" in str(ei.value)


# ---- 参数消毒 ----


class TestParameterSanitize:
    def test_unknown_params_dropped_with_warning(self, regression_csv):
        resp = _run_ml(
            _req(
                "linear_regression",
                regression_csv,
                ["f1", "f2"],
                "y",
                parameters={"n_estimators": 50, "evil": "import os"},
            )
        )
        assert resp.metrics["r2"] > 0.8  # 未被非法参数破坏
        assert resp.warnings and any("n_estimators" in w or "参数" in w for w in resp.warnings)

    def test_out_of_range_param_clamped(self, equipment_csv):
        resp = _run_ml(
            _req(
                "isolation_forest",
                equipment_csv,
                ["downtime_minutes", "alarm_count"],
                None,
                parameters={"contamination": 0.9},
            )
        )
        assert resp.metrics["anomaly_ratio"] <= 0.5, "越界 contamination 应被收敛"


# ---- pipeline execution_mode="ml" 分支（mock LLM + 真沙箱）----

PLAN_ML_JSON = (
    '{"intent":"anomaly","topic":"equipment","tables":["equipment_downtime"],'
    '"metrics":[],"dimensions":[],"filters":[],"time_range":{},"execution_mode":"ml",'
    '"chart_type":null,"expected_output":"检测设备数据中的异常"}'
)

ML_PLAN_ISOLATION = json.dumps(
    {
        "model_type": "isolation_forest",
        "features": ["downtime_minutes", "alarm_count"],
        "target": None,
        "parameters": {"contamination": 0.1},
        "reason": "无监督异常检测",
    },
    ensure_ascii=False,
)

ML_CONCLUSION = (
    "共检出 6 条异常停机记录，集中在停机时长与报警次数显著偏高的设备。"
    "口径说明：异常检测由隔离森林在沙箱内完成。"
)


def _ml_exec_result() -> ExecResult:
    df = _equipment_df(60, 6)
    return ExecResult(
        columns=list(df.columns),
        rows=df.to_dict("records"),
        rowcount=len(df),
        elapsed_ms=5.0,
        truncated=False,
    )


class _FakeLLM:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, *, model_tier="heavy", tools=None, response_format=None):
        self.calls.append({"messages": messages, "model_tier": model_tier})
        if not self.responses:
            raise AssertionError("FakeLLM 响应脚本已耗尽")
        return self.responses.pop(0)

    def chat_stream(self, messages, *, model_tier="heavy"):
        yield from ()


def _resp(content: str):
    from app.llm.client import LLMResponse

    return LLMResponse(
        content=content,
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        provider="fake",
    )


def _parse_frames(frames: list[str]) -> list[Any]:
    from app.schemas.event import SSEEvent

    events = []
    for frame in frames:
        head, sep, data = frame[:-2].partition("\ndata: ")
        assert head.startswith("event: ") and sep
        events.append(SSEEvent(type=head[len("event: "):], data=json.loads(data)))
    return events


def _collect(req, llm, retriever_, cfg_) -> list[str]:
    from app.orchestrator.pipeline import run_analysis

    async def _run() -> list[str]:
        return [frame async for frame in run_analysis(req, llm, retriever_, cfg_)]

    return asyncio.run(_run())


@pytest.fixture
def retriever() -> Retriever:
    return Retriever(DEFAULT_CORPUS_PATH)


@pytest.fixture
def cfg() -> Settings:
    return Settings(sql_max_limit=500)


@pytest.fixture
def patch_executor(monkeypatch):
    def _install(effects: list[Any]) -> dict[str, int]:
        calls = {"n": 0}

        def _fake(sql, session_cfg, **kwargs):
            index = calls["n"]
            calls["n"] += 1
            effect = effects[index] if index < len(effects) else effects[-1]
            if isinstance(effect, Exception):
                raise effect
            return effect

        monkeypatch.setattr("app.orchestrator.pipeline.execute_readonly", _fake)
        return calls

    return _install


@pytest.fixture
def ml_models_dir(tmp_path: Path, monkeypatch):
    """pipeline 测试中模型持久化重定向到临时目录，避免污染 a07-agent/models。"""
    from app.ml import modeler as ml_modeler

    d = tmp_path / "pipe_models"
    d.mkdir()
    monkeypatch.setattr(ml_modeler, "MODELS_DIR", d)
    return d


class TestPipelineMLMode:
    def _req(self) -> Any:
        from app.api.routes import AnalyzeRequest

        return AnalyzeRequest(
            sessionId="s-ml",
            messageId="m-ml",
            question="检测最近一个月设备数据中的异常",
            history=[],
        )

    def test_isolation_forest_flow_events(self, retriever, cfg, patch_executor, ml_models_dir):
        patch_executor([_ml_exec_result()])
        llm = _FakeLLM([
            _resp(PLAN_ML_JSON),
            _resp("SELECT equipment_name, production_line, downtime_minutes, alarm_count, reason "
                  "FROM equipment_downtime WHERE start_time >= DATE_SUB(NOW(), INTERVAL 30 DAY)"),
            _resp(ML_PLAN_ISOLATION),
            _resp(ML_CONCLUSION),
        ])
        events = _parse_frames(_collect(self._req(), llm, retriever, cfg))
        types = [e.type for e in events]

        assert "error" not in types, next((e.data for e in events if e.type == "error"), None)
        assert types[-1] == "done"
        # ① 生成分析方案 → code_generated（模板代码含 IsolationForest）
        code_ev = next(e for e in events if e.type == "code_generated")
        assert code_ev.data["language"] == "python"
        assert "IsolationForest" in code_ev.data["code"]
        # 步骤事件覆盖 生成分析方案/训练评估/结果解释
        step_names = [e.data["name"] for e in events if e.type == "step_started"]
        for name in ("生成分析方案", "训练评估", "结果解释"):
            assert name in step_names, step_names
        # ② ml_result：camelCase 载荷齐全
        ml_ev = next(e for e in events if e.type == "ml_result")
        data = ml_ev.data
        assert data["modelType"] == "isolation_forest"
        assert data["metrics"]["n_anomalies"] >= 1
        assert isinstance(data["featureImportance"], list)
        assert data["plots"] and isinstance(data["modelPath"], str)
        assert data["modelPath"]
        # ③ 异常样本 table 事件（含设备名与异常分数）
        tables = [e for e in events if e.type == "table"]
        assert len(tables) >= 2, "SQL 结果表 + 异常样本表"
        sample_table = tables[-1]
        assert "anomaly_score" in sample_table.data["columns"]
        assert any("equipment_name" in c for c in sample_table.data["columns"])
        # ④ done：insights 含指标，无异常收尾
        done = next(e for e in events if e.type == "done")
        assert done.data["insights"]
        assert not any("失败" in w and "降级" in w for w in done.data["warnings"]), done.data["warnings"]
        assert "text_delta" in types

    def test_anomaly_intent_forces_ml_mode(self, retriever, cfg, patch_executor, ml_models_dir):
        plan_json = PLAN_ML_JSON.replace('"execution_mode":"ml"', '"execution_mode":"sql"')
        patch_executor([_ml_exec_result()])
        llm = _FakeLLM([
            _resp(plan_json),
            _resp("SELECT equipment_name, downtime_minutes, alarm_count FROM equipment_downtime"),
            _resp(ML_PLAN_ISOLATION),
            _resp(ML_CONCLUSION),
        ])
        events = _parse_frames(_collect(self._req(), llm, retriever, cfg))
        types = [e.type for e in events]

        plan_ready = next(e for e in events if e.type == "plan_ready")
        assert plan_ready.data["execution_mode"] == "ml", "anomaly 意图应被纠正为 ml"
        assert "ml_result" in types
        assert "error" not in types

    def test_ml_plan_failure_degrades_to_table(self, retriever, cfg, patch_executor, ml_models_dir):
        patch_executor([_ml_exec_result()])
        llm = _FakeLLM([
            _resp(PLAN_ML_JSON),
            _resp("SELECT 1"),
            _resp("这不是JSON"),   # ML 方案第 1 次失败
            _resp("{{{{"),          # 重试仍失败 → 降级
            _resp("降级后的普通结论。"),
        ])
        events = _parse_frames(_collect(self._req(), llm, retriever, cfg))
        types = [e.type for e in events]

        assert "error" not in types
        assert "ml_result" not in types and "code_generated" not in types
        assert types[-1] == "done"
        done = next(e for e in events if e.type == "done")
        assert any("ML" in w or "建模" in w for w in done.data["warnings"]), done.data["warnings"]
        assert "chart" in types, "降级后应走普通图表路径"

    def test_ml_data_error_degrades_readably(self, retriever, cfg, patch_executor, ml_models_dir):
        # 方案规划把特征填错列 → run_ml 数据校验可读失败 → 降级不崩流
        bad_plan = json.dumps(
            {"model_type": "random_forest", "features": ["no_such_col"], "target": "downtime_minutes"},
            ensure_ascii=False,
        )
        patch_executor([_ml_exec_result()])
        llm = _FakeLLM([
            _resp(PLAN_ML_JSON),
            _resp("SELECT equipment_name, downtime_minutes FROM equipment_downtime"),
            _resp(bad_plan),
            _resp("降级后的普通结论。"),
        ])
        events = _parse_frames(_collect(self._req(), llm, retriever, cfg))
        types = [e.type for e in events]
        assert "error" not in types
        assert types[-1] == "done"
        done = next(e for e in events if e.type == "done")
        assert any("no_such_col" in w for w in done.data["warnings"]), done.data["warnings"]


class TestMLToolRegistryAndRoute:
    def test_tool_registry_has_run_ml_model(self):
        from app.orchestrator.pipeline import TOOL_REGISTRY

        assert "run_ml_model" in TOOL_REGISTRY
        desc, fn = TOOL_REGISTRY["run_ml_model"]
        assert "建模" in desc or "ML" in desc or "ml" in desc
        assert callable(fn)

    def test_ml_rest_endpoint(self, regression_csv, models_dir: Path, monkeypatch):
        from app.ml import modeler as ml_modeler

        monkeypatch.setattr(ml_modeler, "MODELS_DIR", models_dir)
        from app.main import app

        with TestClient(app) as client:
            resp = client.post(
                "/api/agent/ml/run",
                json={
                    "model_type": "random_forest",
                    "features": ["f1", "f2", "cat"],
                    "target": "y",
                    "parameters": {},
                    "data_ref": regression_csv,
                    "question": "用随机森林分析哪些因素对产量影响较大",
                },
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["modelType"] == "random_forest"
        assert body["metrics"]["r2"] > 0.8
        assert body["featureImportance"]
        assert body["modelPath"]

    def test_ml_rest_endpoint_rejects_bad_model_type(self, regression_csv):
        from app.main import app

        with TestClient(app) as client:
            resp = client.post(
                "/api/agent/ml/run",
                json={"model_type": "svm", "features": ["f1"], "data_ref": regression_csv},
            )
        assert resp.status_code == 422

    def test_ml_rest_endpoint_data_error_readable(self, tmp_path: Path):
        from app.main import app

        with TestClient(app) as client:
            resp = client.post(
                "/api/agent/ml/run",
                json={
                    "model_type": "kmeans",
                    "features": ["x1"],
                    "data_ref": str(tmp_path / "no_such.csv"),
                },
            )
        assert resp.status_code == 400
        body = resp.json()
        assert "不存在" in body["message"] or "data_ref" in body["message"]
