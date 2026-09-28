# AI-assisted
"""A2 意图理解与任务规划（docs/03 §3.3 A2 / P1 计划 §Task 5 Step 5.2）。

make_plan：一次 LLM 调用（model_tier=light，response_format=json_object）输出
AnalysisPlan；JSON/结构解析失败重试 1 次，仍失败返回默认 plan
（execution_mode="sql"、chart_type=None、expected_output=原问题）。
LLM 传输层错误（LLMError/LLMNotConfiguredError）不属于"解析失败"，
原样上抛由编排器统一转 error 事件（docs/03 §6）。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import ValidationError

from app.llm.prompts import PLAN_SYSTEM_PROMPT
from app.schemas.plan import AnalysisPlan

logger = logging.getLogger("a07.planner")

_MAX_HISTORY_MESSAGES = 4  # 只携带最近几轮历史，控制 light 档 token 成本

_ALLOWED_TOPICS = {"production", "quality", "equipment", "inventory", "general"}
_ALLOWED_MODES = {"sql", "python", "ml"}
_ALLOWED_CHART_TYPES = {"line", "bar", "pie", "scatter", "table"}

# 规划提示词集中维护于 app/llm/prompts.py（T-012 起含 ml/anomaly/report 意图识别强化）

_RETRY_PROMPT = (
    "上面的输出不是合法 JSON 或字段不合规。请重新只输出一个 JSON 对象，"
    "字段与取值严格遵循系统提示中的字段说明，不要包含 Markdown 代码块或其他文字。"
)


def _default_plan(question: str) -> AnalysisPlan:
    """解析彻底失败时的兜底 plan：按普通 SQL 查询继续走通流程。"""
    return AnalysisPlan(
        intent="other",
        topic=None,
        execution_mode="sql",
        chart_type=None,
        expected_output=question,
    )


def _strip_code_fence(text: str) -> str:
    """剥掉 LLM 可能附带的 ```json 代码块标记。"""
    text = (text or "").strip()
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _coerce(data: dict[str, Any]) -> dict[str, Any]:
    """对 LLM 输出做轻量矫正，减少可自愈字段导致的整体回退。"""
    if not isinstance(data, dict):
        raise ValueError("plan 必须是 JSON 对象")
    if data.get("topic") not in _ALLOWED_TOPICS:
        data["topic"] = None
    if data.get("execution_mode") not in _ALLOWED_MODES:
        data["execution_mode"] = "sql"
    if data.get("chart_type") not in _ALLOWED_CHART_TYPES:
        data["chart_type"] = None
    for key in ("tables", "metrics", "dimensions", "filters"):
        if not isinstance(data.get(key), list):
            data[key] = []
    if not isinstance(data.get("time_range"), dict):
        data["time_range"] = {}
    return data


def _parse_plan(content: str, question: str) -> AnalysisPlan:
    data = json.loads(_strip_code_fence(content))
    plan = AnalysisPlan.model_validate(_coerce(data))
    if not plan.expected_output.strip():
        plan.expected_output = question
    return plan


def _history_messages(history: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """取最近几轮历史（role/content 均转字符串截断），仅供指代消解参考。"""
    messages: list[dict[str, str]] = []
    for item in (history or [])[-_MAX_HISTORY_MESSAGES:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "user")) or "user"
        content = str(item.get("content", ""))[:300]
        if content:
            messages.append({"role": "assistant" if role == "assistant" else "user", "content": content})
    return messages


def make_plan(llm: Any, question: str, history: list[dict[str, Any]] | None = None) -> AnalysisPlan:
    """一次 light 档 LLM 调用产出 AnalysisPlan；解析失败重试 1 次，再失败走默认 plan。"""
    base_messages: list[dict[str, str]] = [
        {"role": "system", "content": PLAN_SYSTEM_PROMPT},
        *_history_messages(history),
        {"role": "user", "content": f"用户问题：{question}\n请输出规划 JSON。"},
    ]
    messages = base_messages
    last_raw = ""
    for attempt in (1, 2):
        try:
            resp = llm.chat(messages, model_tier="light", response_format={"type": "json_object"})
            last_raw = resp.content or ""
            plan = _parse_plan(last_raw, question)
            logger.info(
                "plan_ok attempt=%d intent=%s topic=%s mode=%s chart=%s",
                attempt, plan.intent, plan.topic, plan.execution_mode, plan.chart_type,
            )
            return plan
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            logger.warning("plan_parse_failed attempt=%d error=%s raw=%s", attempt, exc, last_raw[:200])
            messages = [
                *base_messages,
                {"role": "assistant", "content": last_raw[:1000]},
                {"role": "user", "content": _RETRY_PROMPT},
            ]
    logger.warning("plan_fallback_default question=%s", question[:80])
    return _default_plan(question)
