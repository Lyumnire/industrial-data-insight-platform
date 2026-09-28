# AI-assisted
"""A7 六算法 sklearn 沙箱代码模板（P2a 计划 §Task 12.2 / docs/03 §3.3 A7）。

render_ml_template 产出在 A6 沙箱内执行的完整 Python 代码字符串：
- 统一特征工程：数值列 to_numeric 识别 + median 填充 + StandardScaler；类别列 one-hot
  （get_dummies）；常数列/基数>50 的类别列自动剔除；特征工程只读 df、不写任何持久路径。
- 监督算法（linear_regression/logistic_regression/decision_tree/random_forest）：
  train_test_split(test_size=0.25, random_state=42)；decision_tree/random_forest 依
  目标列形态由 modeler 预先解析出 task_type（regression/classification）。
- 评估产出（写入 result，键与 MLResponse 对齐）：metrics / feature_importance /
  plots / predictions_sample / error（业务层失败说明）/ feature_cols / dropped_features。
  回归 MAE/RMSE/R²+预测散点；分类 Accuracy/宏 P/R/F1+混淆矩阵+二分类 ROC 点；
  聚类 轮廓系数+PCA 二维散点按簇着色；异常检测 异常分数分布+阈值线+top-N 异常行。
- 解释：树模型 feature_importances_（按原始特征聚合 one-hot 列）；其余监督模型
  permutation_importance(n_repeats=5)；无监督模型不算特征重要性（空列表）。
- 模型持久化：joblib.dump 到沙箱工作目录相对路径 model.joblib（{"model", "feature_cols",
  "model_type", "task_type"} 打包），由父进程经 run_python(copy_out=...) 收走后移入
  a07-agent/models/——沙箱内绝不写持久路径（红线 R2）。

沙箱约束（app/sandbox/runner.py ALLOWED_MODULES）：模板只准用 pandas/numpy/sklearn/
joblib/json/math（均已在白名单）；模板代码经 @TOKEN@ 替换注入参数（列名/参数值均为
经 modeler 消毒后的字面量，杜绝代码注入）。
"""
from __future__ import annotations

from typing import Any

MODEL_TYPES: tuple[str, ...] = (
    "linear_regression",
    "decision_tree",
    "random_forest",
    "logistic_regression",
    "kmeans",
    "isolation_forest",
)

# 供 ML 方案规划提示词与建模工作台展示的模板目录
ML_TEMPLATE_DESCRIPTIONS: dict[str, str] = {
    "linear_regression": "线性回归（预测连续数值，关系简单可解释）",
    "decision_tree": "决策树（回归/分类自动判别，强可解释）",
    "random_forest": "随机森林（回归/分类自动判别，特征因素分析首选）",
    "logistic_regression": "逻辑回归（二分类/是否类预测）",
    "kmeans": "KMeans 聚类（无标签分群，parameters.n_clusters 指定簇数）",
    "isolation_forest": "隔离森林异常检测（无监督离群点识别，parameters.contamination 指定异常比例）",
}

# 参数经 @TOKEN@ 替换注入（避免 str.format 与代码内花括号的地狱转义）
_TEMPLATE = '''# AI-assisted: A07 沙箱内执行——A7 ML 建模模板（model_type=@MODEL_TYPE@, task_type=@TASK_TYPE@）
import json
import joblib
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest, RandomForestClassifier, RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import (
    accuracy_score, auc, confusion_matrix, f1_score, mean_absolute_error,
    mean_squared_error, precision_score, r2_score, recall_score, roc_curve,
    silhouette_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor


def _rows(_df):
    """DataFrame → list[dict]（JSON 安全标量），供 predictions_sample 使用。"""
    _out = []
    for _, _r in _df.iterrows():
        _row = {}
        for _k, _v in _r.items():
            if pd.isna(_v):
                _row[str(_k)] = None
            elif isinstance(_v, (bool, np.bool_)):
                _row[str(_k)] = bool(_v)
            elif isinstance(_v, (int, np.integer)):
                _row[str(_k)] = int(_v)
            elif isinstance(_v, (float, np.floating)):
                _row[str(_k)] = float(_v)
            else:
                _row[str(_k)] = str(_v)
        _out.append(_row)
    return _out


def _build_features(frame, features):
    """统一特征工程：数值 median 填充+StandardScaler、类别 one-hot；剔除常数/高基数列。

    返回 (X 或 None, 编码后特征列名, 类别列名, 剔除列名)。
    """
    _num, _cat = [], []
    for _c in features:
        _co = pd.to_numeric(frame[_c], errors="coerce")
        if _co.notna().mean() >= 0.5:
            _num.append(_c)
            frame[_c] = _co
        else:
            _cat.append(_c)
            frame[_c] = frame[_c].fillna("缺失").astype(str)
    _drop = [c for c in features if frame[c].nunique(dropna=False) <= 1]
    _drop += [c for c in _cat if frame[c].nunique(dropna=False) > 50]
    _drop = list(dict.fromkeys(_drop))
    if _drop:
        frame = frame.drop(columns=_drop)
    _num = [c for c in _num if c not in _drop]
    _cat = [c for c in _cat if c not in _drop]
    _parts = []
    if _num:
        frame[_num] = frame[_num].fillna(frame[_num].median())
        _scaled = StandardScaler().fit_transform(frame[_num])
        _parts.append(pd.DataFrame(_scaled, columns=_num, index=frame.index))
    if _cat:
        _parts.append(pd.get_dummies(frame[_cat], prefix=_cat, dtype=float))
    if not _parts:
        return None, [], _cat, _drop
    _X = pd.concat(_parts, axis=1)
    return _X, list(_X.columns), _cat, _drop


def _agg_importance(pairs, cat_cols):
    """把 one-hot 展开列的重要性按原始特征求和聚合回 {name, score} 列表。"""
    _agg = {}
    for _n, _s in pairs:
        _src = next((c for c in cat_cols if str(_n).startswith(c + "_")), None)
        _key = _src or str(_n)
        _agg[_key] = _agg.get(_key, 0.0) + float(_s)
    return [{"name": k, "score": round(v, 6)} for k, v in sorted(_agg.items(), key=lambda t: -t[1])]


_features = @FEATURES@
_target = @TARGET@
_model_type = @MODEL_TYPE@
_task_type = @TASK_TYPE@
_params = @PARAMS@
_test_size = float(_params.get("test_size") or 0.25)
_n_est = int(_params.get("n_estimators") or 100)
_tree_kw = {"max_depth": int(_params["max_depth"])} if _params.get("max_depth") else {}
result["model_type"] = _model_type
result["task_type"] = _task_type

_supervised = _task_type in ("regression", "classification")
_error = None
_missing = [c for c in _features if c not in df.columns]
if _target is not None and _target not in df.columns:
    _missing.append(_target)
if _missing:
    _error = "建模数据缺少列：%s；当前数据列为 %s" % (_missing, list(df.columns))
elif _supervised and _target is None:
    _error = "监督学习模型（%s）必须提供 target 目标列" % _model_type

if _error is None:
    _cols = list(dict.fromkeys(_features + ([_target] if _target else [])))
    if not _supervised:
        # 无监督任务（聚类/异常检测）样本行保留全部原始列——异常/分簇结果需可读标识
        # （如设备名、原因等未参与建模的列），top-N 样本表才对业务有意义。
        _cols = list(df.columns)
    _orig = df[_cols].copy()
    _work = df[_cols].copy()
    if _supervised:
        _yt = pd.to_numeric(_work[_target], errors="coerce") if _task_type == "regression" else _work[_target]
        _keep = _yt.notna()
        if float(_keep.mean()) < 0.5:
            _error = "目标列 %s 缺失值过多（有效值不足一半），请更换目标列或先清洗数据" % _target
        else:
            _work = _work.loc[_keep]
            _orig = _orig.loc[_keep]
            _yt = _yt.loc[_keep]
            if _task_type == "classification":
                _yt = _yt.astype(str)

if _error is None and len(_work) < 30:
    _error = "建模样本量不足（%d 行 < 30），请放宽查询时间或筛选条件后重试" % len(_work)

if _error is None:
    _X, _feature_cols, _cat_used, _dropped = _build_features(_work, _features)
    if _X is None:
        _error = "所有特征列均为常数列或全空列，无法建模；请更换特征列后重试"

if _error is not None:
    result["error"] = _error
else:
    _plots = []
    if _dropped:
        result["dropped_features"] = _dropped
    _Xf = _X.astype(float)

    if _task_type == "clustering":
        # ---- KMeans 聚类：全量拟合（无泛化评估），轮廓系数 + PCA 二维散点按簇着色 ----
        _k = int(_params.get("n_clusters") or 3)
        _k = max(2, min(_k, len(_Xf) - 1))
        _model = KMeans(n_clusters=_k, random_state=42, n_init=10)
        _lab = _model.fit_predict(_Xf)
        _sil = 0.0
        if len(set(_lab.tolist())) > 1:
            _sil = float(silhouette_score(_Xf, _lab, sample_size=min(len(_Xf), 1000), random_state=42))
        _metrics = {
            "silhouette": round(_sil, 6),
            "n_clusters": _k,
            "cluster_sizes": {str(i): int((_lab == i).sum()) for i in range(_k)},
            "train_rows": int(len(_Xf)),
        }
        if _Xf.shape[1] >= 2:
            _p2 = PCA(n_components=2, random_state=42).fit_transform(_Xf)
        else:
            _p2 = np.column_stack([_Xf.iloc[:, 0].values, np.zeros(len(_Xf))])
        _cap = min(len(_Xf), 500)
        _series = []
        for _i in range(_k):
            _pts = [
                [float(a), float(b)]
                for a, b, _l in zip(_p2[:_cap, 0], _p2[:_cap, 1], _lab[:_cap])
                if int(_l) == _i
            ]
            _series.append({"name": "簇 %d" % _i, "data": _pts})
        _plots.append({"type": "scatter", "data": {"x": "主成分 1", "y": "主成分 2", "series": _series}})
        _sample = _orig.copy()
        _sample["cluster"] = [int(v) for v in _lab]
        result["predictions_sample"] = _rows(_sample.head(20))
        _imp = []

    elif _task_type == "anomaly":
        # ---- IsolationForest 异常检测：全量拟合，异常分数分布 + 阈值线 + top-N 异常行 ----
        _cont = float(_params.get("contamination") or 0.05)
        _model = IsolationForest(contamination=_cont, random_state=42)
        _model.fit(_Xf)
        _scores = -_model.score_samples(_Xf)      # 越大越异常
        _lab = _model.predict(_Xf)                # -1 = 异常
        _is_anom = _lab == -1
        _threshold = float(-_model.offset_)
        _metrics = {
            "n_anomalies": int(_is_anom.sum()),
            "anomaly_ratio": round(float(_is_anom.mean()), 6),
            "threshold": round(_threshold, 6),
            "score_mean": round(float(_scores.mean()), 6),
            "score_max": round(float(_scores.max()), 6),
            "train_rows": int(len(_Xf)),
        }
        _bins = min(20, max(5, len(_Xf) // 10))
        _counts, _edges = np.histogram(_scores, bins=_bins)
        _plots.append({
            "type": "histogram",
            "data": {
                "bins": [round(float(e), 6) for e in _edges],
                "counts": [int(c) for c in _counts],
                "threshold": _threshold,
            },
        })
        _sample = _orig.copy()
        _sample["anomaly_score"] = [round(float(s), 6) for s in _scores]
        _sample["is_anomaly"] = [bool(b) for b in _is_anom]
        _sample = _sample.sort_values("anomaly_score", ascending=False)
        result["predictions_sample"] = _rows(_sample.head(20))
        _imp = []

    else:
        # ---- 监督学习：train/test split(0.25, seed=42) → 训练评估 ----
        _idx = np.arange(len(_Xf))
        _tr, _te = train_test_split(_idx, test_size=_test_size, random_state=42)
        _Xtr, _Xte = _Xf.iloc[_tr], _Xf.iloc[_te]
        _ytr, _yte = _yt.iloc[_tr], _yt.iloc[_te]
        if _model_type == "linear_regression":
            _model = LinearRegression()
        elif _model_type == "logistic_regression":
            _model = LogisticRegression(max_iter=1000)
        elif _model_type == "decision_tree":
            _model = (DecisionTreeClassifier if _task_type == "classification" else DecisionTreeRegressor)(
                random_state=42, **_tree_kw
            )
        else:
            _model = (RandomForestClassifier if _task_type == "classification" else RandomForestRegressor)(
                n_estimators=_n_est, random_state=42, n_jobs=1, **_tree_kw
            )
        _model.fit(_Xtr, _ytr)
        _pred = _model.predict(_Xte)

        if _task_type == "regression":
            _metrics = {
                "mae": round(float(mean_absolute_error(_yte, _pred)), 6),
                "rmse": round(float(np.sqrt(mean_squared_error(_yte, _pred))), 6),
                "r2": round(float(r2_score(_yte, _pred)), 6),
                "train_rows": int(len(_tr)),
                "test_rows": int(len(_te)),
            }
            _points = [[float(a), float(p)] for a, p in zip(list(_yte)[:200], list(_pred)[:200])]
            _plots.append({"type": "scatter", "data": {"x": "实际值", "y": "预测值", "points": _points}})
        else:
            _cm_labels = sorted(set(_yt.astype(str).tolist()))
            _metrics = {
                "accuracy": round(float(accuracy_score(_yte, _pred)), 6),
                "precision": round(float(precision_score(_yte, _pred, average="macro", zero_division=0)), 6),
                "recall": round(float(recall_score(_yte, _pred, average="macro", zero_division=0)), 6),
                "f1": round(float(f1_score(_yte, _pred, average="macro", zero_division=0)), 6),
                "train_rows": int(len(_tr)),
                "test_rows": int(len(_te)),
            }
            _cm = confusion_matrix(_yte, _pred, labels=_cm_labels)
            _plots.append({
                "type": "heatmap",
                "data": {"labels": _cm_labels, "matrix": [[int(v) for v in row] for row in _cm]},
            })
            if len(_cm_labels) == 2 and hasattr(_model, "predict_proba"):
                _proba = _model.predict_proba(_Xte)[:, 1]
                _fpr, _tpr, _th = roc_curve((_yte == _cm_labels[1]).astype(int), _proba)
                _plots.append({
                    "type": "line",
                    "data": {
                        "x": "fpr",
                        "y": "tpr",
                        "points": [[float(a), float(b)] for a, b in zip(_fpr, _tpr)],
                        "auc": round(float(auc(_fpr, _tpr)), 6),
                    },
                })
        _sample = _orig.iloc[_te].copy()
        _sample["y_true"] = list(_yte)
        _sample["y_pred"] = list(_pred)
        result["predictions_sample"] = _rows(_sample.head(20))

        if _model_type in ("decision_tree", "random_forest"):
            _raw = list(zip(_feature_cols, _model.feature_importances_))
            _imp = _agg_importance(_raw, _cat_used)
        else:
            _pi = permutation_importance(_model, _Xte, _yte, n_repeats=5, random_state=42)
            _imp = _agg_importance(list(zip(_feature_cols, _pi.importances_mean)), _cat_used)

    result["metrics"] = _metrics
    result["plots"] = _plots
    result["feature_importance"] = _imp
    result["feature_cols"] = _feature_cols
    joblib.dump(
        {
            "model": _model,
            "feature_cols": _feature_cols,
            "model_type": _model_type,
            "task_type": _task_type,
        },
        "model.joblib",
    )
    result["model_file"] = "model.joblib"
'''


def render_ml_template(
    model_type: str,
    task_type: str,
    features: list[str],
    target: str | None,
    parameters: dict[str, Any],
) -> str:
    """渲染六算法沙箱代码；model_type 非法抛 ValueError（参数消毒在 modeler 完成）。"""
    if model_type not in MODEL_TYPES:
        raise ValueError(f"未知 ML 模板：{model_type!r}（可用：{', '.join(MODEL_TYPES)}）")
    if task_type not in ("regression", "classification", "clustering", "anomaly"):
        raise ValueError(f"未知任务类型：{task_type!r}")
    return (
        _TEMPLATE.replace("@MODEL_TYPE@", repr(str(model_type)))
        .replace("@TASK_TYPE@", repr(str(task_type)))
        .replace("@FEATURES@", repr([str(f) for f in features]))
        .replace("@TARGET@", repr(str(target) if target else None))
        .replace("@PARAMS@", repr(dict(parameters or {})))
    )
