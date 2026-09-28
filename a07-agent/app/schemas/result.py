# AI-assisted
"""标准分析结果对象（ADR-2 / docs/03 §4）：前端永远只渲染此对象，LLM 原始输出不直接触达前端。

同时是 analysis_results 的持久化形态与 table/chart/code/report 事件的公共载荷骨架；
execution_info 内层字段保持契约规定的 camelCase（durationMs/rowCount/dataSource/truncated）。
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ChartSpec(BaseModel):
    """图表骨架（type 为 ECharts 类型名；字段映射由 chart/builder.py 模板拼装，docs/02 §1.5）。"""

    type: str
    x: Optional[str] = None
    y: list[str] = Field(default_factory=list)
    series: list[Any] = Field(default_factory=list)


class ExecutionInfo(BaseModel):
    """执行信息；字段名与 docs/03 §4 契约 JSON 完全一致（camelCase，勿改成 snake_case）。"""

    durationMs: int = 0
    rowCount: int = 0
    dataSource: str = ""
    truncated: bool = False


class AnalysisResult(BaseModel):
    """一次分析的标准结果：表格 + 图 + 结论 + 警示 + SQL/代码 + 执行元信息。"""

    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    chart: Optional[ChartSpec] = None
    insights: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    sql: Optional[str] = None
    python_code: Optional[str] = None
    execution_info: ExecutionInfo = Field(default_factory=ExecutionInfo)
