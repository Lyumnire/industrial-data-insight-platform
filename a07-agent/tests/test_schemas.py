# AI-assisted
"""契约一致性测试：SSE 事件模型 / AnalysisPlan / 标准分析结果对象与 docs/03 §4 严格对齐。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.event import EVENT_TYPES, SSEEvent
from app.schemas.plan import AnalysisPlan
from app.schemas.result import AnalysisResult

# docs/03 §4 事件表全集（前端↔引擎边界契约，冻结）
CONTRACT_EVENT_TYPES = [
    "task_started", "step_started", "step_finished",
    "plan_ready", "text_delta",
    "sql_generated", "sql_validated", "sql_executing", "sql_completed",
    "code_generated", "table", "chart_building", "chart", "ml_result",
    "insight_generating", "report", "clarify", "done", "error",
]


def test_sse_frame_format() -> None:
    ev = SSEEvent(type="sql_generated", data={"sql": "SELECT 1", "stepId": "s1"})
    assert ev.to_sse_frame() == 'event: sql_generated\ndata: {"sql": "SELECT 1", "stepId": "s1"}\n\n'


def test_sse_all_contract_types_accepted() -> None:
    assert set(CONTRACT_EVENT_TYPES) == set(EVENT_TYPES)  # 无遗漏、无多余
    for t in CONTRACT_EVENT_TYPES:
        frame = SSEEvent(type=t, data={}).to_sse_frame()
        assert frame.startswith(f"event: {t}\ndata: ")
        assert frame.endswith("\n\n")


def test_sse_unknown_type_rejected() -> None:
    with pytest.raises(ValidationError):
        SSEEvent(type="not_in_contract", data={})


def test_plan_defaults_and_validation() -> None:
    plan = AnalysisPlan(intent="查询统计", execution_mode="sql")
    assert plan.topic is None and plan.chart_type is None and plan.ml_task is None
    assert plan.tables == [] and plan.metrics == [] and plan.dimensions == []
    assert plan.filters == [] and plan.time_range == {} and plan.expected_output == ""

    plan2 = AnalysisPlan(intent="x", topic="quality", chart_type="bar",
                         time_range={"start": "2026-01-01"}, execution_mode="ml")
    assert plan2.topic == "quality" and plan2.chart_type == "bar" and plan2.ml_task is None

    with pytest.raises(ValidationError):
        AnalysisPlan(intent="x", execution_mode="spark")  # 非法执行模式
    with pytest.raises(ValidationError):
        AnalysisPlan(intent="x", chart_type="3d")         # 非法图表类型
    with pytest.raises(ValidationError):
        AnalysisPlan(intent="x", topic="sales")           # 非法主题枚举


def test_result_contract_keys() -> None:
    data = AnalysisResult().model_dump()
    assert set(data) == {"columns", "rows", "summary", "chart", "insights",
                         "warnings", "sql", "python_code", "execution_info"}
    # execution_info 内层字段为契约规定的 camelCase（docs/03 §4）
    assert set(data["execution_info"]) == {"durationMs", "rowCount", "dataSource", "truncated"}
    assert data["chart"] is None and data["python_code"] is None

    r2 = AnalysisResult(
        columns=["process_name"],
        rows=[{"process_name": "焊接", "yield_rate": 90.5}],
        chart={"type": "bar", "x": "process_name", "y": ["yield_rate"], "series": []},
        insights=["焊接良率低于均值"],
        execution_info={"durationMs": 120, "rowCount": 5, "dataSource": "mes_demo", "truncated": False},
    )
    assert r2.chart is not None and r2.chart.type == "bar"
    assert r2.execution_info.rowCount == 5 and r2.execution_info.truncated is False
