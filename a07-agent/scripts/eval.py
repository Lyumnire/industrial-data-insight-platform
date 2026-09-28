# AI-assisted
"""T-023 P4 评测集跑分：读题库 → 调 analyze（JWT+server 或直连 agent）→ 按规则判定 → 报告。

用法（仓库根或任意目录）:
  # mock 脚手架（不调 LLM，验证题库+判定器+报告链路）
  python a07-agent/scripts/eval.py --mode mock

  # 真链路：经 a07-server:8080 JWT + SSE 透传（推荐，完整链路）
  python a07-agent/scripts/eval.py --mode via-server

  # 真链路：直连 agent:8100（调试/费用敏感时）
  python a07-agent/scripts/eval.py --mode via-agent

  # 分批 / 抽样
  python a07-agent/scripts/eval.py --mode via-server --ids EVAL-001,EVAL-003
  python a07-agent/scripts/eval.py --mode via-server --sample 12
  python a07-agent/scripts/eval.py --mode via-server --domain quality --difficulty L1

输出:
  a07-agent/logs/eval_<ts>/   每题 events.log + results.json（gitignore）
  docs/assets/eval_T023_<mode>_<ts>.md|.json  评测报告（白名单允许）

纪律: 禁止为提高通过率改评测题迁就实现；失败题原样记入报告与工单。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
AGENT_DIR = SCRIPT_DIR.parent
REPO_ROOT = AGENT_DIR.parent
DEFAULT_DATASET = SCRIPT_DIR / "eval_dataset.json"
DEFAULT_LOG_DIR = AGENT_DIR / "logs" / "eval"
DEFAULT_REPORT_DIR = REPO_ROOT / "docs" / "assets"

# 致命错误码：出现即视为链路失败（业务 clarify/空结果不算）
FATAL_ERROR_HINTS = (
    "INTERNAL_ERROR",
    "LLM_ERROR",
    "LLM_NOT_CONFIGURED",
    "TABLE_MISSING",
    "DB_ERROR",
    "SQL_EXEC",
    "Agent 引擎不可达",
)


# ---------------------------------------------------------------------------
# 题库
# ---------------------------------------------------------------------------

def load_dataset(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("items") or []
    if not items:
        raise ValueError(f"评测题库为空: {path}")
    return items


# ---------------------------------------------------------------------------
# SSE 调用
# ---------------------------------------------------------------------------

def login(base: str, username: str = "admin", password: str = "admin123") -> str:
    req = urllib.request.Request(
        f"{base}/api/auth/login",
        data=json.dumps({"username": username, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    body = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    if body.get("code") != 0:
        raise RuntimeError(f"login failed: {body}")
    return body["data"]["token"]


def parse_sse_text(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    event_type: str | None = None
    data_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        if line.startswith("event:"):
            if event_type is not None:
                events.append({"type": event_type, "data": _try_json("\n".join(data_lines))})
            event_type = line[6:].strip()
            data_lines = []
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
        elif line == "":
            if event_type is not None:
                events.append({"type": event_type, "data": _try_json("\n".join(data_lines))})
                event_type = None
                data_lines = []
    if event_type is not None:
        events.append({"type": event_type, "data": _try_json("\n".join(data_lines))})
    return events


def _try_json(text: str) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text[:500]


def stream_analyze(
    url: str,
    question: str,
    token: str | None,
    session_id: str,
    history: list[dict[str, Any]] | None = None,
    timeout: int = 240,
) -> list[dict[str, Any]]:
    payload = {
        "sessionId": session_id,
        "messageId": f"{session_id}-m1",
        "question": question,
        "history": history or [],
        "context": {"budget": 8000, "mode": "standard"},
    }
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    events: list[dict[str, Any]] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if "event-stream" not in ctype:
                raw = resp.read().decode("utf-8", errors="replace")
                return [{"type": "non_sse_response", "data": {"content_type": ctype, "body": raw[:2000]}}]
            event_type = None
            data_lines: list[str] = []
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if line.startswith("event:"):
                    if event_type is not None:
                        events.append({"type": event_type, "data": _try_json("\n".join(data_lines))})
                    event_type = line[6:].strip()
                    data_lines = []
                elif line.startswith("data:"):
                    data_lines.append(line[5:].strip())
                elif line == "":
                    if event_type is not None:
                        events.append({"type": event_type, "data": _try_json("\n".join(data_lines))})
                        event_type = None
                        data_lines = []
            if event_type is not None:
                events.append({"type": event_type, "data": _try_json("\n".join(data_lines))})
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        events.append({"type": "http_error", "data": {"status": e.code, "body": body[:2000]}})
    except Exception as e:  # noqa: BLE001 — 评测需记录任意失败
        events.append({"type": "client_error", "data": {"error": str(e)}})
    return events


# ---------------------------------------------------------------------------
# 判定器
# ---------------------------------------------------------------------------

def _events_of(events: list[dict[str, Any]], etype: str) -> list[dict[str, Any]]:
    return [e for e in events if e.get("type") == etype]


def _all_sql(events: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for e in events:
        if e.get("type") in ("sql_generated", "sql_validated", "sql_executing", "sql_completed"):
            sql = (e.get("data") or {}).get("sql")
            if sql:
                out.append(str(sql))
    return out


def _table_cols(events: list[dict[str, Any]]) -> list[str]:
    cols: list[str] = []
    for e in _events_of(events, "table"):
        cols.extend(str(c) for c in ((e.get("data") or {}).get("columns") or []))
    return cols


def _table_has_rows(events: list[dict[str, Any]]) -> bool:
    for e in _events_of(events, "table"):
        if (e.get("data") or {}).get("rows"):
            return True
    return False


def _plan(events: list[dict[str, Any]]) -> dict[str, Any]:
    evs = _events_of(events, "plan_ready")
    data = evs[0].get("data") if evs else None
    return data if isinstance(data, dict) else {}


def _text_stream(events: list[dict[str, Any]]) -> str:
    return "".join(
        str((e.get("data") or {}).get("delta") or "") for e in _events_of(events, "text_delta")
    )


def _report_md(events: list[dict[str, Any]]) -> str:
    return "".join(
        str((e.get("data") or {}).get("markdown") or "") for e in _events_of(events, "report")
    )


def _ml_blob(events: list[dict[str, Any]]) -> str:
    parts = []
    for e in _events_of(events, "ml_result"):
        parts.append(json.dumps(e.get("data"), ensure_ascii=False, default=str))
    return "\n".join(parts)


def _content_blob(events: list[dict[str, Any]]) -> str:
    """SQL + 表头 + 结论文本 + 报告 markdown + 步骤 detail 的合成检索面。"""
    parts: list[str] = []
    parts.extend(_all_sql(events))
    parts.append(" ".join(_table_cols(events)))
    parts.append(_text_stream(events))
    parts.append(_report_md(events))
    for e in events:
        if e.get("type") in ("step_started", "step_finished", "clarify"):
            d = e.get("data") or {}
            parts.append(f"{d.get('name') or ''} {d.get('detail') or ''} {d.get('question') or ''}")
    return "\n".join(parts)


def _has_any_keyword(haystack: str, keywords: list[str]) -> bool:
    low = haystack.lower()
    return any(k.lower() in low for k in keywords)


def _fatal_errors(events: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    for e in events:
        t = e.get("type")
        d = e.get("data") or {}
        blob = json.dumps(d, ensure_ascii=False) if isinstance(d, dict) else str(d)
        if t in ("error", "http_error", "client_error", "non_sse_response", "step_finished"):
            for hint in FATAL_ERROR_HINTS:
                if hint in blob:
                    found.append(hint)
        if t == "error" and isinstance(d, dict) and d.get("code"):
            found.append(str(d["code"]))
    return sorted(set(found))


def _eval_rule(events: list[dict[str, Any]], rule: str | dict[str, Any]) -> tuple[bool, str]:
    if isinstance(rule, str):
        name, params = rule, {}
    else:
        name = str(rule.get("rule") or "")
        params = {k: v for k, v in rule.items() if k != "rule"}

    types = [e.get("type") for e in events]
    plan = _plan(events)
    sql_blob = "\n".join(_all_sql(events))
    content = _content_blob(events)

    if name == "has_plan_ready":
        return ("plan_ready" in types), "has_plan_ready"
    if name == "has_sql_generated":
        return ("sql_generated" in types), name
    if name == "has_sql_validated":
        return ("sql_validated" in types), name
    if name == "has_sql_completed":
        return ("sql_completed" in types), name
    if name == "has_table_nonempty":
        return _table_has_rows(events), name
    if name == "has_chart":
        return ("chart" in types), name
    if name == "has_text_delta":
        return ("text_delta" in types), name
    if name == "has_report":
        return ("report" in types), name
    if name == "has_insight_generating":
        return ("insight_generating" in types), name
    if name == "has_code_generated":
        return ("code_generated" in types), name
    if name == "has_ml_result":
        return ("ml_result" in types), name
    if name == "has_clarify":
        return ("clarify" in types), name
    if name == "has_no_sql_completed":
        return ("sql_completed" not in types), name
    if name == "has_no_sql_generated":
        return ("sql_generated" not in types), name
    if name == "has_no_table":
        return ("table" not in types), name
    if name == "has_event":
        return (str(params.get("event")) in types), f"has_event:{params.get('event')}"
    if name == "has_no_event":
        return (str(params.get("event")) not in types), f"has_no_event:{params.get('event')}"
    if name == "has_any_event":
        wanted = params.get("events") or []
        return any(w in types for w in wanted), f"has_any_event:{wanted}"
    if name == "min_event_count":
        et, mn = str(params.get("event")), int(params.get("min") or 1)
        return (types.count(et) >= mn), f"min_event_count:{et}>={mn}"
    if name == "sql_mentions_any":
        kws = params.get("keywords") or []
        return _has_any_keyword(sql_blob, kws), f"sql_mentions_any:{kws}"
    if name == "sql_mentions_all":
        kws = params.get("keywords") or []
        low = sql_blob.lower()
        return all(k.lower() in low for k in kws), f"sql_mentions_all:{kws}"
    if name == "table_columns_any":
        kws = params.get("keywords") or []
        cols = " ".join(_table_cols(events))
        return _has_any_keyword(cols, kws), f"table_columns_any:{kws}"
    if name == "text_contains_any":
        kws = params.get("keywords") or []
        return _has_any_keyword(_text_stream(events), kws), f"text_contains_any:{kws}"
    if name == "content_contains_any":
        kws = params.get("keywords") or []
        return _has_any_keyword(content, kws), f"content_contains_any:{kws}"
    if name == "ml_result_has_any":
        kws = params.get("keywords") or []
        blob = _ml_blob(events)
        if not blob:
            return False, "ml_result_has_any:<empty>"
        return _has_any_keyword(blob, kws), f"ml_result_has_any:{kws}"
    if name == "plan_intent_is":
        return (plan.get("intent") == params.get("value")), f"plan_intent_is:{params.get('value')}"
    if name == "plan_intent_in":
        return (plan.get("intent") in (params.get("values") or [])), f"plan_intent_in:{params.get('values')}"
    if name == "plan_topic_is":
        return (plan.get("topic") == params.get("value")), f"plan_topic_is:{params.get('value')}"
    if name == "plan_mode_is":
        return (plan.get("execution_mode") == params.get("value")), f"plan_mode_is:{params.get('value')}"
    if name == "plan_mode_in":
        return (plan.get("execution_mode") in (params.get("values") or [])), f"plan_mode_in:{params.get('values')}"
    if name == "ends_with_done":
        return (types[-1] == "done") if types else False, name
    if name == "no_fatal_error":
        fatals = _fatal_errors(events)
        return (not fatals), (name if not fatals else f"no_fatal_error:found={fatals}")
    if name == "any_of":
        sub = params.get("rules") or []
        reasons = []
        for r in sub:
            ok, reason = _eval_rule(events, r)
            reasons.append(reason)
            if ok:
                return True, f"any_of:pass via {reason}"
        return False, f"any_of:none passed {reasons}"

    return False, f"unknown_rule:{name}"


def judge_events(events: list[dict[str, Any]], item: dict[str, Any]) -> dict[str, Any]:
    rules = item.get("pass_rules") or []
    failed: list[str] = []
    passed_rules: list[str] = []
    for rule in rules:
        ok, reason = _eval_rule(events, rule)
        if ok:
            passed_rules.append(reason)
        else:
            failed.append(reason)
    return {
        "pass": len(failed) == 0,
        "failed_rules": failed,
        "passed_rules": passed_rules,
        "event_types": [e.get("type") for e in events],
        "type_counts": dict(Counter(e.get("type") for e in events)),
        "fatal_errors": _fatal_errors(events),
        "plan": _plan(events),
        "sqls": _all_sql(events),
        "table_columns": _table_cols(events),
    }


# ---------------------------------------------------------------------------
# mock 事件脚手架（无 LLM，仅验证题库/判定/报告链路）
# ---------------------------------------------------------------------------

def synthesize_mock_events(item: dict[str, Any], *, force_pass: bool = True) -> list[dict[str, Any]]:
    """按 execution_hint 合成一组事件。force_pass=True 时尽量满足 pass_rules。"""
    q = item.get("question") or ""
    hint = item.get("execution_hint") or "sql"
    tables = item.get("expected_tables") or ["process_output"]
    main_table = tables[0] if tables else "process_output"
    domain = item.get("domain") or "general"
    topic = item.get("expected_topic") or (domain if domain in ("production", "quality", "equipment", "inventory") else "general")
    if topic in ("cross", "security", None):
        topic = "general"

    if not force_pass:
        return [
            {"type": "task_started", "data": {"question": q}},
            {"type": "error", "data": {"code": "INTERNAL_ERROR", "message": "mock intentional fail"}},
            {"type": "done", "data": {}},
        ]

    def plan(mode: str, intent: str, chart: str | None = "bar") -> dict[str, Any]:
        return {
            "type": "plan_ready",
            "data": {
                "intent": intent,
                "topic": topic if topic != "general" else None,
                "tables": tables,
                "metrics": [],
                "execution_mode": mode,
                "chart_type": chart,
                "expected_output": q,
            },
        }

    def sql_events(sql: str, cols: list[str], row: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {"type": "sql_generated", "data": {"sql": sql, "attempt": 0}},
            {"type": "sql_validated", "data": {"sql": sql, "valid": True, "message": "ok"}},
            {"type": "sql_executing", "data": {"sql": sql}},
            {"type": "sql_completed", "data": {"sql": sql, "rowCount": 1, "elapsedMs": 3}},
            {"type": "table", "data": {"columns": cols, "rows": [row], "total": 1}},
        ]

    events: list[dict[str, Any]] = [
        {"type": "task_started", "data": {"sessionId": "mock", "question": q}},
        {"type": "step_started", "data": {"stepId": "1", "name": "意图理解", "detail": "mock"}},
    ]

    # 从 pass_rules 反推需要填充的关键词，保证脚手架可通过自身题库
    rules = item.get("pass_rules") or []
    need_sql_kws: list[str] = []
    need_col_kws: list[str] = []
    need_text_kws: list[str] = []
    need_content_kws: list[str] = []
    need_ml_kws: list[str] = []
    for rule in rules:
        r = rule if isinstance(rule, dict) else {"rule": rule}
        name = r.get("rule")
        kws = r.get("keywords") or []
        if name == "sql_mentions_any":
            need_sql_kws.extend(kws)
        elif name == "table_columns_any":
            need_col_kws.extend(kws)
        elif name == "text_contains_any":
            need_text_kws.extend(kws)
        elif name == "content_contains_any":
            need_content_kws.extend(kws)
        elif name == "ml_result_has_any":
            need_ml_kws.extend(kws)

    sql = f"SELECT * FROM {main_table} /* mock {' '.join(need_sql_kws[:8])} */ LIMIT 10"
    # 列名：把关键词做成伪列名，满足 table_columns_any
    cols = ["id"]
    for kw in list(dict.fromkeys(need_col_kws))[:8]:
        cols.append(re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff]+", "_", kw) or "col")
    row = {c: (1 if c == "id" else "mock") for c in cols}

    if hint == "refuse":
        events.append(plan("sql", "refuse", None))
        events.append({"type": "step_finished", "data": {"stepId": "1", "name": "意图理解", "detail": "refuse"}})
        text = "平台为只读分析，无法执行删除/修改等写操作。" + " ".join(need_text_kws[:4])
        events.append({"type": "text_delta", "data": {"delta": text, "index": 0}})
        events.append({"type": "done", "data": {"summary": {"conclusion": text}}})
        return events

    if hint == "report":
        events.append(plan("sql", "report", None))
        n = 3
        for rule in rules:
            if isinstance(rule, dict) and rule.get("rule") == "min_event_count" and rule.get("event") == "sql_completed":
                n = max(n, int(rule.get("min") or 3))
        for i in range(n):
            events.extend(sql_events(sql, cols, row))
        events.append({"type": "insight_generating", "data": {"reportId": "rpt_mock", "topic": topic, "steps": n}})
        md = f"# {topic}分析报告\n\nmock 报告正文 {' '.join(need_content_kws[:4])}\n"
        events.append({"type": "report", "data": {"reportId": "rpt_mock", "markdown": md, "topic": topic}})
        events.append({"type": "done", "data": {"summary": {"report": md}}})
        return events

    if hint == "ml":
        events.append(plan("ml", "ml", None))
        events.extend(sql_events(sql, cols, row))
        events.append({"type": "code_generated", "data": {"language": "python", "code": "print('mock')", "source": "mock"}})
        ml_data = {
            "modelType": "random_forest",
            "model_type": "random_forest",
            "taskType": "classification",
            "feature_importance": [{"feature": "mock", "importance": 0.5}],
            "metrics": {"accuracy": 0.8},
            "note": " ".join(need_ml_kws) or "mock",
        }
        events.append({"type": "ml_result", "data": ml_data})
        text = "建模完成。" + " ".join(need_text_kws + need_content_kws)
        events.append({"type": "text_delta", "data": {"delta": text, "index": 0}})
        events.append({"type": "done", "data": {"summary": {"conclusion": text}}})
        return events

    if hint == "python":
        intent = "correlation" if item.get("task_type") == "correlation" else "compare"
        events.append(plan("python", intent, "scatter"))
        events.extend(sql_events(sql, cols, row))
        events.append({"type": "code_generated", "data": {"language": "python", "code": "import pandas as pd", "source": "mock"}})
        events.append(
            {
                "type": "chart",
                "data": {"type": "scatter", "x": "x", "y": "y", "series": [{"name": "y", "type": "scatter", "data": [[1, 2]]}], "option": {"series": [{"data": [[1, 2]]}]}},
            }
        )
        text = "相关性分析完成 corr=0.42 相关系数 scatter。" + " ".join(need_text_kws + need_content_kws)
        events.append({"type": "text_delta", "data": {"delta": text, "index": 0}})
        events.append({"type": "done", "data": {"summary": {"conclusion": text}}})
        return events

    # 默认 sql 路径
    intent = {"trend": "trend", "rank": "rank", "metric": "query"}.get(str(item.get("task_type")), "query")
    chart_type = "line" if item.get("task_type") == "trend" else "bar"
    events.append(plan("sql", intent, chart_type))
    events.extend(sql_events(sql, cols, row))
    # 若规则要求 chart
    if any((r if isinstance(r, dict) else {"rule": r}).get("rule") == "has_chart" for r in rules):
        events.append(
            {
                "type": "chart",
                "data": {"type": chart_type, "x": cols[0], "y": cols[-1], "series": [{"name": cols[-1], "type": chart_type, "data": [1]}], "option": {"series": [{"data": [1]}], "xAxis": {}}},
            }
        )
    text = "分析完成。" + " ".join(need_text_kws + need_content_kws)
    events.append({"type": "text_delta", "data": {"delta": text, "index": 0}})
    events.append({"type": "done", "data": {"summary": {"conclusion": text}}})
    return events


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

def _slug(q: str) -> str:
    keep = [ch if (ch.isalnum() or ch in "_-") else "_" for ch in q]
    return "".join(keep)[:40]


def write_reports(
    results: list[dict[str, Any]],
    *,
    mode: str,
    out_dir: Path,
    dataset_version: str,
    tag: str = "T023",
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(results)
    passed = sum(1 for r in results if r.get("pass"))
    pass_rate = (passed / total * 100) if total else 0.0
    by_domain: dict[str, list[bool]] = {}
    by_diff: dict[str, list[bool]] = {}
    by_type: dict[str, list[bool]] = {}
    for r in results:
        by_domain.setdefault(r.get("domain") or "?", []).append(bool(r.get("pass")))
        by_diff.setdefault(r.get("difficulty") or "?", []).append(bool(r.get("pass")))
        by_type.setdefault(r.get("task_type") or "?", []).append(bool(r.get("pass")))

    def _rate_block(m: dict[str, list[bool]]) -> list[str]:
        lines = ["| 分组 | 通过/总数 | 通过率 |", "|---|---:|---:|"]
        for k in sorted(m):
            v = m[k]
            ok = sum(v)
            lines.append(f"| {k} | {ok}/{len(v)} | {ok/len(v)*100:.1f}% |")
        return lines

    failures = [r for r in results if not r.get("pass")]
    _tm = re.fullmatch(r"T(\d+)", tag)
    title_tag = f"T-{_tm.group(1)}" if _tm else tag
    lines: list[str] = [
        f"# {title_tag} P4 评测集跑分报告",
        "",
        f"- 版本: `{dataset_version}` · 模式: **{mode}** · 题量: **{total}**",
        f"- 通过: **{passed}/{total}** · 通过率: **{pass_rate:.1f}%**",
        f"- 纪律: 评测题不因实现失败而修改；失败题原样进入 bug-log 候选池。",
        "",
        "## 分组通过率",
        "",
        *_rate_block(by_domain),
        "",
        *_rate_block(by_type),
        "",
        *_rate_block(by_diff),
        "",
        "## 失败题清单",
        "",
    ]
    if not failures:
        lines.append("（本轮无失败题）")
    else:
        lines.extend(
            [
                "| ID | 领域 | 难度 | 类型 | 问题 | 失败规则 | 事件摘要 |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for r in failures:
            q = str(r.get("question") or "").replace("|", "\\|")
            rules = "; ".join(r.get("failed_rules") or [])[:180].replace("|", "\\|")
            types = ",".join(list(r.get("type_counts") or {}).keys())[:80]
            lines.append(
                f"| {r.get('id')} | {r.get('domain')} | {r.get('difficulty')} | {r.get('task_type')} | {q} | {rules} | {types} |"
            )

    lines.extend(["", "## 全量结果", "", "| ID | 领域 | 难度 | 类型 | 结果 | 问题 | 备注 |", "|---|---|---|---|---|---|---|"])
    for r in results:
        mark = "✅" if r.get("pass") else "❌"
        q = str(r.get("question") or "").replace("|", "\\|")
        note = str(r.get("source") or "").replace("|", "\\|")
        lines.append(
            f"| {r.get('id')} | {r.get('domain')} | {r.get('difficulty')} | {r.get('task_type')} | {mark} | {q} | {note} |"
        )

    lines.extend(["", "## 失败题详情（供 bug-log / 缺陷池）", ""])
    for r in failures:
        lines.append(f"### {r.get('id')} · {r.get('question')}")
        lines.append("")
        lines.append(f"- 来源: {r.get('source')} · 领域: {r.get('domain')} · 难度: {r.get('difficulty')} · 类型: {r.get('task_type')}")
        lines.append(f"- 期望表: {r.get('expected_tables')} · 期望事件: {r.get('expected_events')}")
        lines.append(f"- 失败规则: {r.get('failed_rules')}")
        lines.append(f"- 事件类型: {r.get('type_counts')}")
        if r.get("plan"):
            lines.append(f"- plan: `{json.dumps(r.get('plan'), ensure_ascii=False)[:300]}`")
        if r.get("sqls"):
            lines.append(f"- SQL: `{str(r['sqls'][0])[:240]}`")
        if r.get("table_columns"):
            lines.append(f"- 表列: {r.get('table_columns')[:12]}")
        if r.get("fatal_errors"):
            lines.append(f"- 致命错误: {r.get('fatal_errors')}")
        if r.get("error"):
            lines.append(f"- 调用错误: {r.get('error')}")
        lines.append(f"- notes: {r.get('notes')}")
        lines.append("")

    summary = {
        "tag": tag,
        "version": dataset_version,
        "mode": mode,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round(pass_rate, 2),
        "by_domain": {k: {"passed": sum(v), "total": len(v)} for k, v in by_domain.items()},
        "by_task_type": {k: {"passed": sum(v), "total": len(v)} for k, v in by_type.items()},
        "by_difficulty": {k: {"passed": sum(v), "total": len(v)} for k, v in by_diff.items()},
        "failures": [
            {
                "id": r.get("id"),
                "question": r.get("question"),
                "domain": r.get("domain"),
                "difficulty": r.get("difficulty"),
                "task_type": r.get("task_type"),
                "failed_rules": r.get("failed_rules"),
                "type_counts": r.get("type_counts"),
                "fatal_errors": r.get("fatal_errors"),
                "error": r.get("error"),
                "source": r.get("source"),
                "notes": r.get("notes"),
            }
            for r in failures
        ],
        "results": results,
    }

    md_path = out_dir / f"eval_{tag}_{mode}_{time.strftime('%Y%m%d-%H%M%S')}.md"
    json_path = md_path.with_suffix(".json")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return md_path, json_path


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _select_items(
    items: list[dict[str, Any]],
    *,
    ids: list[str] | None,
    domain: str | None,
    difficulty: str | None,
    sample: int | None,
) -> list[dict[str, Any]]:
    selected = list(items)
    if ids:
        idset = set(ids)
        selected = [it for it in selected if it.get("id") in idset]
    if domain:
        selected = [it for it in selected if it.get("domain") == domain]
    if difficulty:
        selected = [it for it in selected if it.get("difficulty") == difficulty]
    if sample and sample < len(selected):
        # 分层抽样：按 domain 轮询
        by_dom: dict[str, list[dict[str, Any]]] = {}
        for it in selected:
            by_dom.setdefault(str(it.get("domain")), []).append(it)
        picked: list[dict[str, Any]] = []
        keys = list(by_dom)
        idx = 0
        while len(picked) < sample:
            k = keys[idx % len(keys)]
            bucket = by_dom[k]
            if bucket:
                picked.append(bucket.pop(0))
            idx += 1
            if all(not b for b in by_dom.values()):
                break
        selected = picked
    return selected


def run_one(
    item: dict[str, Any],
    *,
    mode: str,
    url: str,
    token: str | None,
    timeout: int,
    ts: str,
    event_dir: Path,
) -> dict[str, Any]:
    iid = item["id"]
    question = item["question"]
    history = item.get("history") or []
    print(f"\n===== {iid} [{item.get('domain')}/{item.get('difficulty')}/{item.get('task_type')}] {question[:40]} =====")
    t0 = time.time()
    if mode == "mock":
        events = synthesize_mock_events(item, force_pass=True)
        elapsed = 0.0
        call_error = None
    else:
        session_id = f"eval-{ts}-{iid}"
        try:
            events = stream_analyze(url, question, token, session_id, history=history, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            events = [{"type": "client_error", "data": {"error": str(e)}}]
        elapsed = round(time.time() - t0, 1)
        call_error = None
        if events and events[0].get("type") in ("client_error", "http_error", "non_sse_response"):
            call_error = json.dumps(events[0].get("data"), ensure_ascii=False)[:400]

    verdict = judge_events(events, item)
    result = {
        "id": iid,
        "question": question,
        "source": item.get("source"),
        "domain": item.get("domain"),
        "task_type": item.get("task_type"),
        "difficulty": item.get("difficulty"),
        "expected_tables": item.get("expected_tables"),
        "expected_events": item.get("expected_events"),
        "notes": item.get("notes"),
        "pass": verdict["pass"],
        "failed_rules": verdict["failed_rules"],
        "passed_rules": verdict["passed_rules"],
        "type_counts": verdict["type_counts"],
        "event_types": verdict["event_types"],
        "fatal_errors": verdict["fatal_errors"],
        "plan": verdict["plan"],
        "sqls": verdict["sqls"][:3],
        "table_columns": verdict["table_columns"][:20],
        "elapsed_s": elapsed,
        "mode": mode,
        "error": call_error,
    }
    event_dir.mkdir(parents=True, exist_ok=True)
    log_path = event_dir / f"{iid}_{_slug(question)}.events.log"
    with log_path.open("w", encoding="utf-8") as f:
        f.write(f"# id: {iid}\n# question: {question}\n# mode: {mode}\n# elapsed_s: {elapsed}\n# pass: {result['pass']}\n")
        f.write(f"# failed_rules: {result['failed_rules']}\n")
        for e in events:
            f.write(f"event: {e.get('type')}\ndata: {json.dumps(e.get('data'), ensure_ascii=False, default=str)}\n\n")
    mark = "PASS" if result["pass"] else "FAIL"
    print(f"  -> {mark} elapsed={elapsed}s types={verdict['type_counts']}")
    if not result["pass"]:
        print(f"     failed_rules={result['failed_rules']}")
        if call_error:
            print(f"     error={call_error}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T-023 P4 评测集跑分")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--mode", choices=["via-server", "via-agent", "mock"], default="mock")
    parser.add_argument("--server-base", default="http://localhost:8080")
    parser.add_argument("--agent-base", default="http://localhost:8100")
    parser.add_argument("--ids", default="", help="逗号分隔题目 ID，如 EVAL-001,EVAL-003")
    parser.add_argument("--domain", default="", help="production|quality|equipment|inventory|cross|security")
    parser.add_argument("--difficulty", default="", help="L1|L2|L3")
    parser.add_argument("--sample", type=int, default=0, help="分层抽样 N 题（0=不抽样）")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--tag", default="T023", help="报告文件/标题标签，如 T031")
    args = parser.parse_args(argv)

    items = load_dataset(args.dataset)
    version = json.loads(args.dataset.read_text(encoding="utf-8")).get("version", "unknown")
    ids = [x.strip() for x in args.ids.split(",") if x.strip()] or None
    selected = _select_items(
        items,
        ids=ids,
        domain=args.domain or None,
        difficulty=args.difficulty or None,
        sample=args.sample or None,
    )
    if not selected:
        print("筛选结果为空", file=sys.stderr)
        return 2

    mode = args.mode
    token = None
    url = args.agent_base
    if mode == "via-server":
        url = f"{args.server_base}/api/chat/analyze"
        token = login(args.server_base)
        print(f"mode=via-server url={url} token_ok items={len(selected)}")
    elif mode == "via-agent":
        url = f"{args.agent_base}/api/agent/analyze"
        print(f"mode=via-agent url={url} items={len(selected)}")
    else:
        print(f"mode=mock items={len(selected)}")

    ts = time.strftime("%Y%m%d-%H%M%S")
    run_dir = args.log_dir / f"{mode}_{ts}"
    event_dir = run_dir / "events"

    results: list[dict[str, Any]] = []
    partial_path = run_dir / "results.ndjson"
    run_dir.mkdir(parents=True, exist_ok=True)
    for item in selected:
        # 报告/建模更耗时，放大超时
        timeout = args.timeout
        if item.get("execution_hint") in ("report", "ml", "python"):
            timeout = max(timeout, 360)
        result = run_one(
            item,
            mode=mode,
            url=url,
            token=token,
            timeout=timeout,
            ts=ts,
            event_dir=event_dir,
        )
        results.append(result)
        with partial_path.open("a", encoding="utf-8") as pf:
            pf.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")

    md_path, json_path = write_reports(
        results, mode=mode, out_dir=args.report_dir, dataset_version=version, tag=args.tag
    )
    total = len(results)
    passed = sum(1 for r in results if r.get("pass"))
    print(f"\n[summary] mode={mode} pass={passed}/{total} rate={passed/total*100:.1f}%")
    print(f"[report] {md_path}")
    print(f"[json]   {json_path}")
    print(f"[events] {event_dir}")
    failed_ids = [r["id"] for r in results if not r.get("pass")]
    if failed_ids:
        print(f"[failed] {','.join(failed_ids)}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
