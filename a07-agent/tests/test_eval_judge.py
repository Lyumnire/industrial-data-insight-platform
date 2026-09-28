# AI-assisted
"""T-023 评测集脚手架测试：题库结构 + 判定规则 + mock 事件合成。

不依赖真实 LLM / MySQL / 服务进程；真链路跑分由 scripts/eval.py 手工执行。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = AGENT_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from eval import (  # noqa: E402
    judge_events,
    load_dataset,
    parse_sse_text,
    synthesize_mock_events,
    write_reports,
)

DATASET_PATH = SCRIPTS_DIR / "eval_dataset.json"
# 评测题库属内部材料，不随公开仓库分发：缺失时整组跳过而非失败
pytestmark = pytest.mark.skipif(
    not DATASET_PATH.exists(), reason="eval dataset not shipped in this repository"
)

REQUIRED_FIELDS = (
    "id",
    "question",
    "domain",
    "task_type",
    "difficulty",
    "expected_tables",
    "expected_events",
    "execution_hint",
    "pass_rules",
    "notes",
)


@pytest.fixture(scope="module")
def dataset() -> list[dict]:
    return load_dataset(DATASET_PATH)


def test_dataset_version_and_size(dataset: list[dict]) -> None:
    raw = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    assert raw.get("version"), "题库必须带 version"
    assert len(dataset) >= 30, f"评测集题量不足: {len(dataset)}"


def test_dataset_required_fields(dataset: list[dict]) -> None:
    for item in dataset:
        for field in REQUIRED_FIELDS:
            assert field in item, f"{item.get('id')} 缺字段 {field}"
        assert item["id"].startswith("EVAL-")
        assert item["question"].strip()
        assert item["pass_rules"], f"{item['id']} 缺 pass_rules"
        assert item["difficulty"] in {"L1", "L2", "L3"}
        assert item["domain"] in {
            "production",
            "quality",
            "equipment",
            "inventory",
            "cross",
            "security",
        }
        assert item["task_type"] in {
            "query",
            "statistic",
            "metric",
            "trend",
            "rank",
            "compare",
            "correlation",
            "ml",
            "report",
            "refuse",
            "multi_turn",
        }


def test_dataset_unique_ids(dataset: list[dict]) -> None:
    ids = [it["id"] for it in dataset]
    assert len(ids) == len(set(ids))


def test_dataset_domain_and_task_coverage(dataset: list[dict]) -> None:
    domains = {it["domain"] for it in dataset}
    for d in ("production", "quality", "equipment", "inventory"):
        assert d in domains, f"缺业务域 {d}"
    types = {it["task_type"] for it in dataset}
    for t in ("query", "metric", "trend", "report", "ml", "refuse"):
        assert t in types, f"缺任务类型 {t}"
    difficulties = {it["difficulty"] for it in dataset}
    assert {"L1", "L2", "L3"} <= difficulties
    # 覆盖指定业务场景关键词
    blob = "".join(it["question"] for it in dataset)
    for kw in ("良率", "产量", "停机", "库存", "工单", "呆滞", "不良"):
        assert kw in blob, f"评测集未覆盖关键词: {kw}"


def test_dataset_covers_docs01_scenarios(dataset: list[dict]) -> None:
    """docs/01 §7 核心验收场景必须在题库中有来源标注。"""
    sources = " ".join(str(it.get("source") or "") for it in dataset)
    for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12):
        assert f"§7-{n}" in sources, f"缺 docs/01 §7 场景 {n}"


def test_multi_turn_items_have_history(dataset: list[dict]) -> None:
    for it in dataset:
        if it["task_type"] == "multi_turn":
            assert it.get("history"), f"{it['id']} 多轮题缺 history"
            assert any(h.get("role") == "user" for h in it["history"])


def test_refuse_rules_forbid_sql_and_table(dataset: list[dict]) -> None:
    refuses = [it for it in dataset if it["task_type"] == "refuse"]
    assert refuses, "评测集须含拒绝类题"
    for it in refuses:
        flat = [
            r if isinstance(r, str) else r.get("rule")
            for r in it["pass_rules"]
        ]
        assert "has_no_sql_completed" in flat, f"{it['id']} 未禁止 sql_completed"
        assert "has_no_table" in flat, f"{it['id']} 未禁止 table"


def test_judge_pass_on_mock_synthetic(dataset: list[dict]) -> None:
    """mock 合成事件应能通过自身题库判定（脚手架自洽）。"""
    for item in dataset:
        events = synthesize_mock_events(item, force_pass=True)
        verdict = judge_events(events, item)
        assert verdict["pass"], f"{item['id']} mock 应通过: {verdict['failed_rules']}"


def test_judge_fail_when_events_missing() -> None:
    item = {
        "id": "EVAL-TMP",
        "question": "请分析各工序的良率。",
        "pass_rules": [
            "has_plan_ready",
            "has_sql_completed",
            "has_table_nonempty",
            "has_chart",
            "ends_with_done",
            "no_fatal_error",
        ],
    }
    events = [
        {"type": "task_started", "data": {}},
        {"type": "plan_ready", "data": {"intent": "query", "execution_mode": "sql"}},
        {"type": "done", "data": {}},
    ]
    verdict = judge_events(events, item)
    assert not verdict["pass"]
    assert "has_sql_completed" in verdict["failed_rules"]
    assert "has_table_nonempty" in verdict["failed_rules"]
    assert "has_chart" in verdict["failed_rules"]


def test_judge_fail_on_fatal_error() -> None:
    item = {
        "id": "EVAL-TMP2",
        "question": "q",
        "pass_rules": ["has_plan_ready", "no_fatal_error"],
    }
    events = [
        {"type": "plan_ready", "data": {}},
        {"type": "error", "data": {"code": "INTERNAL_ERROR", "message": "boom"}},
        {"type": "done", "data": {}},
    ]
    verdict = judge_events(events, item)
    assert not verdict["pass"]
    assert any("no_fatal_error" in r for r in verdict["failed_rules"])


def test_judge_refuse_path() -> None:
    item = {
        "id": "EVAL-TMP3",
        "question": "删除所有质量检验数据。",
        "pass_rules": [
            "has_plan_ready",
            "has_no_sql_completed",
            "has_no_table",
            "has_text_delta",
            {"rule": "text_contains_any", "keywords": ["拒绝", "只读"]},
            "ends_with_done",
            "no_fatal_error",
        ],
    }
    good = synthesize_mock_events(
        {
            "id": "EVAL-TMP3",
            "question": "删除所有质量检验数据。",
            "execution_hint": "refuse",
            "domain": "security",
            "task_type": "refuse",
            "pass_rules": item["pass_rules"],
            "expected_tables": [],
        },
        force_pass=True,
    )
    assert judge_events(good, item)["pass"]

    bad = good + [{"type": "sql_completed", "data": {"sql": "SELECT 1"}}]
    verdict = judge_events(bad, item)
    # has_no_sql_completed 会被违反（追加事件后）
    assert any("has_no_sql_completed" in r for r in verdict["failed_rules"])


def test_parse_sse_frames() -> None:
    text = (
        'event: plan_ready\ndata: {"intent":"query","execution_mode":"sql"}\n\n'
        'event: table\ndata: {"columns":["a"],"rows":[{"a":1}]}\n\n'
        'event: done\ndata: {}\n\n'
    )
    events = parse_sse_text(text)
    assert [e["type"] for e in events] == ["plan_ready", "table", "done"]
    assert events[0]["data"]["intent"] == "query"


def test_write_reports_markdown_and_json(tmp_path: Path, dataset: list[dict]) -> None:
    results = []
    for item in dataset[:3]:
        events = synthesize_mock_events(item, force_pass=True)
        verdict = judge_events(events, item)
        results.append(
            {
                "id": item["id"],
                "question": item["question"],
                "domain": item["domain"],
                "task_type": item["task_type"],
                "difficulty": item["difficulty"],
                "source": item.get("source"),
                "notes": item.get("notes"),
                "expected_tables": item.get("expected_tables"),
                "expected_events": item.get("expected_events"),
                "pass": verdict["pass"],
                "failed_rules": verdict["failed_rules"],
                "type_counts": verdict["type_counts"],
                "plan": verdict["plan"],
                "sqls": verdict["sqls"],
                "table_columns": verdict["table_columns"],
                "fatal_errors": verdict["fatal_errors"],
                "error": None,
            }
        )
    md_path, json_path = write_reports(
        results, mode="mock", out_dir=tmp_path, dataset_version="t023-v1"
    )
    assert md_path.exists() and md_path.suffix == ".md"
    assert json_path.exists()
    md = md_path.read_text(encoding="utf-8")
    assert "T-023" in md
    assert "通过率" in md
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["total"] == 3
    assert payload["passed"] == 3
