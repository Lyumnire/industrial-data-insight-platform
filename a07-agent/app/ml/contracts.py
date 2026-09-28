# AI-assisted
"""A7 统一 ML 任务契约（P2a 计划 §Task 12.1 / docs/03 §3.3 A7、§4 ml_result 事件）。

MLRequest（建模请求）→ 沙箱训练 → MLResponse（建模结果）。pydantic 强校验（红线 R7）：
model_type 限定六算法字面量；features 非空；data_ref 为只读 SQL 或结果 CSV 路径。
MLResponse 字段与 docs/03 §4 ml_result 事件载荷逐字段对齐（feature_importance/plots
结构化子模型；camelCase 别名在 modeler.ml_payload 统一补充，勿在此改名）。
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

ModelType = Literal[
    "linear_regression",
    "decision_tree",
    "random_forest",
    "logistic_regression",
    "kmeans",
    "isolation_forest",
]

# task_type：由 modeler 依 model_type 与目标列数据解析（决策树/随机森林自动判别）
TaskType = Literal["regression", "classification", "clustering", "anomaly"]


class MLRequest(BaseModel):
    """一次建模任务的统一请求契约（§Task 12.1）。

    data_ref 两种形态（由 modeler 解析）：
    - 只读 SELECT SQL 文本（经 sqlguard 白名单校验后以只读账号执行，红线 R1）；
    - 引擎可访问的 CSV 文件路径（SQL 结果导出物）。
    """

    model_type: ModelType
    features: list[str] = Field(min_length=1)
    target: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    data_ref: str

    @field_validator("features")
    @classmethod
    def _features_stripped(cls, value: list[str]) -> list[str]:
        cleaned = [str(f).strip() for f in value if str(f).strip()]
        if not cleaned:
            raise ValueError("features 不能为空（至少一个特征列名）")
        return cleaned


class FeatureImportance(BaseModel):
    """单个特征的贡献度（树模型 feature_importances_ / 其余 permutation_importance）。"""

    name: str
    score: float


class MLPlot(BaseModel):
    """建模结果图数据（ml_result.plots 元素）：type 为 ECharts 类型名，data 为绘图数据。"""

    type: str
    data: dict[str, Any] = Field(default_factory=dict)


class MLResponse(BaseModel):
    """一次建模任务的统一结果契约（§Task 12.1；ml_result 事件与 /api/agent/ml/run 共用）。"""

    task_id: str
    model_type: str
    task_type: TaskType
    metrics: dict[str, Any] = Field(default_factory=dict)
    feature_importance: list[FeatureImportance] = Field(default_factory=list)
    plots: list[MLPlot] = Field(default_factory=list)
    predictions_sample: list[dict[str, Any]] = Field(default_factory=list)
    explanation: str = ""
    model_path: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
