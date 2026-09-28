# AI-assisted
"""AnalysisPlan：编排器 A2 每轮分析先产出的结构化规划对象（docs/03 §3.3 A2）。

pydantic 强校验（红线 R7）：LLM 输出解析失败时由 planner 走默认 plan（Task 5），
本模型只负责把合法结构与非法结构严格分开。
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Topic = Literal["production", "quality", "equipment", "inventory", "general"]
ExecutionMode = Literal["sql", "python", "ml"]
ChartType = Literal["line", "bar", "pie", "scatter", "table"]


class AnalysisPlan(BaseModel):
    """一次分析任务的规划：意图、主题、涉及的表/指标/维度/过滤/时间窗、执行方式与预期产出。"""

    intent: str
    topic: Optional[Topic] = None
    tables: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    time_range: dict[str, Any] = Field(default_factory=dict)
    execution_mode: ExecutionMode = "sql"
    ml_task: Optional[dict[str, Any]] = None
    chart_type: Optional[ChartType] = None
    expected_output: str = ""
