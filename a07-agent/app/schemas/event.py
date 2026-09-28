# AI-assisted
"""SSE 事件协议模型（docs/03 §4：前端↔引擎的边界契约，先冻结再并行开发）。

帧格式固定为 `event: <type>\ndata: <json>\n\n`；事件类型白名单与 docs/03 §4
事件表一一对应，未知类型在模型层即拒绝（契约纪律：类型变更须走 docs/api 变更流程）。
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, field_validator

EVENT_TYPES: frozenset[str] = frozenset({
    # 步骤时间线
    "task_started", "step_started", "step_finished",
    # 分析档案（右侧 Drawer）
    "plan_ready",
    # 流式文本（结论/报告）
    "text_delta",
    # SQL 链路
    "sql_generated", "sql_validated", "sql_executing", "sql_completed",
    # 代码 / 结果卡片
    "code_generated", "table", "chart_building", "chart", "ml_result",
    # 报告
    "insight_generating", "report",
    # 澄清 / 结束 / 错误
    "clarify", "done", "error",
})


class SSEEvent(BaseModel):
    """单条 SSE 事件：type 为契约白名单内的事件名，data 为该事件的 JSON 载荷。"""

    type: str
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def _type_in_contract(cls, v: str) -> str:
        if v not in EVENT_TYPES:
            raise ValueError(
                f"未知 SSE 事件类型: {v!r}；允许值见 docs/03 §4 事件表（{sorted(EVENT_TYPES)}）"
            )
        return v

    def to_sse_frame(self) -> str:
        """序列化为一帧 SSE 文本：`event: <type>\\ndata: <json>\\n\\n`。"""
        return f"event: {self.type}\ndata: {json.dumps(self.data, ensure_ascii=False, default=str)}\n\n"
