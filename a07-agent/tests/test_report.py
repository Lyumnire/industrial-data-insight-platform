# AI-assisted
"""T-013 A8 反幻觉报告生成测试（P2a 计划 §Task 13，先于实现编写——严格 TDD）。

覆盖面：
- 主题固定查询集：四大主题各自步骤 + general/None 兜底
- 数字一致性校验（ADR-3/R5）：编造数字被标记并被剔除、可溯源数字保留、
  差值/占比容差放行、日期与时间表述豁免
- 结构完整性：十大小节齐备、关键指标可溯源、生成时间
- pipeline 报告流程（mock LLM + 打桩执行器）：固定查询集顺序执行各发事件 →
  insight_generating → report(markdown+reportId) → done 存报告全文；
  关键词触发（问题含"总结"）；单步查询失败不阻断报告
- 工具注册表 generate_report
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.config import Settings
from app.retriever import DEFAULT_CORPUS_PATH, Retriever
from app.sqlguard.executor import ExecResult, SQLExecutionError

# ---- 固定步骤结果（数字一致性/结构测试共用）----

STEPS: list[dict[str, Any]] = [
    {
        "name": "缺陷分布",
        "description": "统计各缺陷类型的不良数量与占比",
        "sql": "SELECT defect_type, SUM(defect_qty) AS defect_qty FROM quality_inspections GROUP BY defect_type",
        "ok": True,
        "error": None,
        "columns": ["defect_type", "defect_qty"],
        "rows": [
            {"defect_type": "划痕", "defect_qty": 210},
            {"defect_type": "气泡", "defect_qty": 150},
            {"defect_type": "色差", "defect_qty": 100},
        ],
        "stats": {"rowCount": 3},
    },
    {
        "name": "良率趋势",
        "description": "按日统计良率趋势",
        "sql": "SELECT production_date, ROUND(...) AS yield_rate FROM process_output GROUP BY production_date",
        "ok": True,
        "error": None,
        "columns": ["production_date", "yield_rate"],
        "rows": [
            {"production_date": "2026-09-14", "yield_rate": 97.06},
            {"production_date": "2026-09-15", "yield_rate": 96.12},
        ],
        "stats": {"rowCount": 2},
    },
]


class TestTopicQuerySets:
    def test_quality_set(self):
        from app.report.builder import TOPIC_QUERY_SETS

        names = [q["name"] for q in TOPIC_QUERY_SETS["quality"]]
        assert names == ["缺陷分布", "良率趋势", "周不良TOP"]
        assert all(q["question"].strip() for q in TOPIC_QUERY_SETS["quality"])

    def test_production_equipment_inventory_sets(self):
        from app.report.builder import TOPIC_QUERY_SETS

        assert [q["name"] for q in TOPIC_QUERY_SETS["production"]] == ["产量趋势", "产线对比"]
        assert [q["name"] for q in TOPIC_QUERY_SETS["equipment"]] == ["停机TOP", "设备异常"]
        inv_names = [q["name"] for q in TOPIC_QUERY_SETS["inventory"]]
        assert inv_names == ["库存周转概览", "库存余额分布", "工单完成概览"]
        inv_text = " ".join(q["question"] for q in TOPIC_QUERY_SETS["inventory"])
        # T-017：问题文本须点名 T-015 两表，便于 NL2SQL 在语料落地后直接命中
        assert "inventory_records" in inv_text
        assert "production_orders" in inv_text

    def test_fallback_for_general_and_none(self):
        from app.report.builder import report_query_set

        fallback = report_query_set(None)
        assert fallback and all("name" in q and "question" in q for q in fallback)
        assert report_query_set("general") == fallback
        assert report_query_set("quality") != fallback


class TestNumberVerification:
    def test_clean_report_passes(self):
        from app.report.builder import verify_report_numbers

        md = (
            "## 七、核心发现\n"
            "划痕类缺陷不良数量为 210 件，为本周最高；气泡类为 150 件。\n"
            "## 八、异常发现\n"
            "良率最低日为 2026-09-15，当日良率 96.12%。\n"
        )
        assert verify_report_numbers(md, STEPS) == []

    def test_fabricated_number_flagged(self):
        from app.report.builder import verify_report_numbers

        md = (
            "## 七、核心发现\n"
            "划痕类缺陷不良数量为 210 件。另有虚报不良 88.88 件的记录。\n"
        )
        assert verify_report_numbers(md, STEPS) == ["88.88"]

    def test_derived_difference_allowed(self):
        from app.report.builder import verify_report_numbers

        md = "## 七、核心发现\n划痕类比气泡类多 60 件，良率趋势中两日相差 0.94 个百分点。\n"
        assert verify_report_numbers(md, STEPS) == []

    def test_dates_and_time_words_exempt(self):
        from app.report.builder import verify_report_numbers

        md = (
            "## 四、时间范围\n本周（2026-09-14 至 2026-09-20），共 7 天。\n"
            "## 十、生成时间\n2026-09-20 02:40:11\n"
        )
        assert verify_report_numbers(md, STEPS) == []

    def test_sanitize_removes_violating_sentence_keeps_valid(self):
        from app.report.builder import sanitize_report

        md = (
            "## 七、核心发现\n"
            "划痕类缺陷不良数量为 210 件，为本周最高。另有虚报不良 88.88 件的记录。气泡类为 150 件。\n"
        )
        cleaned, warnings = sanitize_report(md, STEPS)
        assert "88.88" not in cleaned
        assert "210 件" in cleaned and "150 件" in cleaned
        assert warnings and any("88.88" in w for w in warnings)


class TestReportStructure:
    def test_ten_sections_present(self):
        from app.report.builder import build_report

        md = build_report("quality", "生成本周质量分析报告", STEPS)
        for heading in (
            "报告主题", "分析问题", "数据来源", "时间范围", "关键指标",
            "图表锚点", "核心发现", "异常发现", "结论建议", "生成时间",
        ):
            assert heading in md, f"报告缺少小节：{heading}"
        assert "生成本周质量分析报告" in md
        assert "缺陷分布" in md and "良率趋势" in md

    def test_key_metrics_traceable_and_fallback_narrative(self):
        from app.report.builder import build_report, verify_report_numbers

        md = build_report("quality", "生成本周质量分析报告", STEPS)
        # 关键指标/发现中的数字全部来自 steps（缺陷合计 210+150+100=460）
        assert "460" in md
        assert verify_report_numbers(md, STEPS) == [], "无 LLM 报告的数字必须全部可溯源"


# ---- pipeline 报告流程（mock LLM + 打桩执行器）----

PLAN_REPORT_JSON = (
    '{"intent":"report","topic":"quality","tables":["quality_inspections"],"metrics":[],'
    '"dimensions":[],"filters":[],"time_range":{},"execution_mode":"sql",'
    '"chart_type":null,"expected_output":"本周质量分析报告"}'
)

SQL_DEFECT = "SELECT defect_type, SUM(defect_qty) AS defect_qty FROM quality_inspections GROUP BY defect_type ORDER BY defect_qty DESC"
SQL_TREND = "SELECT production_date, ROUND(SUM(qualified_qty)/NULLIF(SUM(produced_qty),0)*100,2) AS yield_rate FROM process_output GROUP BY production_date ORDER BY production_date"
SQL_TOP = "SELECT process_name, SUM(defect_qty) AS defect_qty FROM quality_inspections GROUP BY process_name ORDER BY defect_qty DESC LIMIT 5"

REPORT_NARRATIVE_JSON = json.dumps(
    {
        "findings": "本周缺陷合计 460 件，其中划痕类 210 件居首，气泡类 150 件次之。",
        "anomalies": "良率近两日分别为 97.06 与 96.12，未发现明显异常。",
        "suggestions": "建议重点关注划痕类缺陷的工序来源，并保持对良率的日度跟踪。",
    },
    ensure_ascii=False,
)


def _exec_defect() -> ExecResult:
    rows = [
        {"defect_type": "划痕", "defect_qty": 210},
        {"defect_type": "气泡", "defect_qty": 150},
        {"defect_type": "色差", "defect_qty": 100},
    ]
    return ExecResult(columns=["defect_type", "defect_qty"], rows=rows, rowcount=3, elapsed_ms=4.0, truncated=False)


def _exec_trend() -> ExecResult:
    rows = [
        {"production_date": "2026-09-14", "yield_rate": 97.06},
        {"production_date": "2026-09-15", "yield_rate": 96.12},
    ]
    return ExecResult(columns=["production_date", "yield_rate"], rows=rows, rowcount=2, elapsed_ms=4.0, truncated=False)


def _exec_top() -> ExecResult:
    rows = [{"process_name": "焊接", "defect_qty": 188}, {"process_name": "注塑", "defect_qty": 122}]
    return ExecResult(columns=["process_name", "defect_qty"], rows=rows, rowcount=2, elapsed_ms=4.0, truncated=False)


class _FakeLLM:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, *, model_tier="heavy", tools=None, response_format=None):
        self.calls.append({"messages": messages, "model_tier": model_tier, "response_format": response_format})
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


class TestPipelineReportMode:
    def _req(self, question: str = "生成本周质量分析报告") -> Any:
        from app.api.routes import AnalyzeRequest

        return AnalyzeRequest(sessionId="s-rpt", messageId="m-rpt", question=question, history=[])

    def _script(self) -> tuple[_FakeLLM, list[Any]]:
        llm = _FakeLLM([
            _resp(PLAN_REPORT_JSON),
            _resp(SQL_DEFECT),
            _resp(SQL_TREND),
            _resp(SQL_TOP),
            _resp(REPORT_NARRATIVE_JSON),
        ])
        effects = [_exec_defect(), _exec_trend(), _exec_top()]
        return llm, effects

    def test_report_flow_events_and_archive(self, retriever, cfg, patch_executor):
        llm, effects = self._script()
        patch_executor(effects)
        events = _parse_frames(_collect(self._req(), llm, retriever, cfg))
        types = [e.type for e in events]

        assert "error" not in types, next((e.data for e in events if e.type == "error"), None)
        assert types[-1] == "done"
        # 固定查询集顺序执行：三个 table + 各步 sql 链路事件
        assert types.count("table") == 3
        assert types.count("sql_completed") == 3
        # insight_generating → report(markdown+reportId)
        ig = next(e for e in events if e.type == "insight_generating")
        assert ig.data["reportId"]
        report_ev = next(e for e in events if e.type == "report")
        markdown = report_ev.data["markdown"]
        assert report_ev.data["reportId"].startswith("rpt_")
        for heading in ("报告主题", "数据来源", "关键指标", "核心发现", "结论建议", "生成时间"):
            assert heading in markdown
        # LLM 叙述进入报告且数字可溯源
        assert "460" in markdown and "210" in markdown
        # done 存报告全文 + reportId
        done = next(e for e in events if e.type == "done")
        assert done.data["summary"]["report"] == markdown
        assert done.data.get("report") == markdown and done.data.get("reportId") == report_ev.data["reportId"]
        # LLM 分层：light 规划 + 3 次 SQL + 1 次报告叙述（全部 heavy）
        assert [c["model_tier"] for c in llm.calls] == ["light", "heavy", "heavy", "heavy", "heavy"]

    def test_keyword_trigger_activates_report_flow(self, retriever, cfg, patch_executor):
        # 规划器把"总结"类问题规划成普通查询（intent=query）时，编排层按关键词强制进报告流程
        plan_json = PLAN_REPORT_JSON.replace('"intent":"report"', '"intent":"query"')
        patch_executor([_exec_defect(), _exec_trend(), _exec_top()])
        llm = _FakeLLM([
            _resp(plan_json),
            _resp(SQL_DEFECT),
            _resp(SQL_TREND),
            _resp(SQL_TOP),
            _resp(REPORT_NARRATIVE_JSON),
        ])
        events = _parse_frames(_collect(self._req("帮我总结一下本周质量情况"), llm, retriever, cfg))
        types = [e.type for e in events]
        assert "report" in types and types[-1] == "done"
        assert "error" not in types

    def test_step_failure_does_not_block_report(self, retriever, cfg, patch_executor):
        # 第 2 个查询连续 3 次（初次+2 次回喂重生成）执行失败 → 该步记失败，其余步骤照常
        patch_executor([
            _exec_defect(),
            SQLExecutionError("[执行失败] Table gone"),
            SQLExecutionError("[执行失败] Table gone"),
            SQLExecutionError("[执行失败] Table gone"),
            _exec_top(),
        ])
        llm = _FakeLLM([
            _resp(PLAN_REPORT_JSON),
            _resp(SQL_DEFECT),
            _resp(SQL_TREND),
            _resp(SQL_TREND),   # 失败后重试一次仍失败（回喂重生成）
            _resp(SQL_TREND),   # 第 3 次仍失败 → 该步放弃
            _resp(SQL_TOP),
            _resp(REPORT_NARRATIVE_JSON),
        ])
        events = _parse_frames(_collect(self._req(), llm, retriever, cfg))
        types = [e.type for e in events]

        assert "error" not in types, next((e.data for e in events if e.type == "error"), None)
        assert types[-1] == "done"
        failed_steps = [
            e for e in events
            if e.type == "step_finished" and "失败" in str(e.data.get("detail", ""))
        ]
        assert failed_steps, "失败步骤应有 step_finished 说明"
        report_ev = next(e for e in events if e.type == "report")
        assert "460" in report_ev.data["markdown"]
        done = next(e for e in events if e.type == "done")
        assert done.data["summary"]["report"]


class TestReportToolRegistry:
    def test_generate_report_registered(self):
        from app.orchestrator.pipeline import TOOL_REGISTRY

        assert "generate_report" in TOOL_REGISTRY
        desc, fn = TOOL_REGISTRY["generate_report"]
        assert callable(fn)
        assert "报告" in desc


# ---- T-017 库存主题准备：缺表可读错误 + 基础设施错误不重生成 SQL ----

PLAN_INVENTORY_REPORT_JSON = (
    '{"intent":"report","topic":"inventory","tables":["inventory_records","production_orders"],'
    '"metrics":[],"dimensions":[],"filters":[],"time_range":{},"execution_mode":"sql",'
    '"chart_type":null,"expected_output":"本周库存分析报告"}'
)

SQL_INV_TURNOVER = (
    "SELECT warehouse, SUM(outbound_qty) AS outbound_qty, AVG(inventory_qty) AS avg_inventory "
    "FROM inventory_records GROUP BY warehouse ORDER BY outbound_qty DESC"
)
SQL_INV_BALANCE = (
    "SELECT warehouse, product_name, inventory_qty FROM inventory_records "
    "ORDER BY inventory_qty DESC"
)
SQL_ORDER_COMPLETION = (
    "SELECT production_line, SUM(planned_qty) AS planned_qty, SUM(completed_qty) AS completed_qty "
    "FROM production_orders GROUP BY production_line ORDER BY completed_qty DESC"
)

_MISSING_TABLE_ERR = SQLExecutionError(
    "[执行失败] ProgrammingError: (1146, \"Table 'mes_demo.inventory_records' doesn't exist\")"
)
_INFRA_ERR = SQLExecutionError(
    "[执行失败] OperationalError: (2003, \"Can't connect to MySQL server on '127.0.0.1'\")"
)


class TestSqlExecErrorClassification:
    def test_missing_table_detected(self):
        from app.orchestrator.pipeline import _sql_exec_error_kind

        assert _sql_exec_error_kind(_MISSING_TABLE_ERR) == "missing_table"
        assert _sql_exec_error_kind(
            SQLExecutionError("[执行失败] ProgrammingError: (1146, \"Table 'mes_demo.production_orders' doesn't exist\")")
        ) == "missing_table"

    def test_infra_error_detected(self):
        from app.orchestrator.pipeline import _sql_exec_error_kind

        assert _sql_exec_error_kind(_INFRA_ERR) == "infra"
        assert _sql_exec_error_kind(
            SQLExecutionError("[执行失败] OperationalError: (1045, \"Access denied for user\")")
        ) == "infra"

    def test_sql_logic_error_still_retriable(self):
        from app.orchestrator.pipeline import _sql_exec_error_kind

        assert _sql_exec_error_kind(
            SQLExecutionError("[执行失败] ProgrammingError: (1054, \"Unknown column 'foo'\")")
        ) is None
        assert _sql_exec_error_kind(SQLExecutionError("[执行失败] some syntax near SELECT")) is None


class TestInventoryReportReadiness:
    """T-017：数据组尚未落表时，库存主题报告错误可读、不崩溃、不无谓重试 SQL。"""

    def _req(self, question: str = "生成本周库存分析报告") -> Any:
        from app.api.routes import AnalyzeRequest

        return AnalyzeRequest(sessionId="s-inv", messageId="m-inv", question=question, history=[])

    def test_inventory_set_points_to_t015_tables(self):
        from app.report.builder import TOPIC_QUERY_SETS, report_query_set

        qs = report_query_set("inventory")
        assert qs is TOPIC_QUERY_SETS["inventory"]
        assert len(qs) == 3  # BUG-015：库存报告设计固定 3 步（周转/余额/工单完成）

    def test_inventory_report_runs_all_three_steps(self, retriever, cfg, patch_executor):
        """BUG-015：库存报告 3 步全部成功时，编排层必须顺序执行并各发 table 事件。

        真链路（T-019）曾只跑 1/3 步——根因为引擎进程陈旧（启动早于 T-017 代码入库），
        非编排逻辑短路。本用例锁定：topic=inventory → 3 次 SQL 执行 + 3 个 table +
        三步 step_started 名称齐全 + report/done 收口。
        """
        from app.report.builder import TOPIC_QUERY_SETS

        inv_qs = TOPIC_QUERY_SETS["inventory"]
        assert [s["name"] for s in inv_qs] == ["库存周转概览", "库存余额分布", "工单完成概览"]

        effects = [_exec_trend(), _exec_top(), _exec_defect()]
        calls = patch_executor(effects)
        llm = _FakeLLM([
            _resp(PLAN_INVENTORY_REPORT_JSON),
            _resp(SQL_INV_TURNOVER),
            _resp(SQL_INV_BALANCE),
            _resp(SQL_ORDER_COMPLETION),
            # 不提供叙述脚本 → FakeLLM 耗尽 → 确定性兜底（数字天然可溯源）
        ])
        events = _parse_frames(_collect(self._req(), llm, retriever, cfg))
        types = [e.type for e in events]
        assert "error" not in types, next((e.data for e in events if e.type == "error"), None)
        assert types[-1] == "done"
        # 3 步各产生 table / sql_completed
        assert types.count("table") == 3, f"库存报告应出 3 个 table，实际 types={types}"
        assert types.count("sql_completed") == 3
        # 三个报告步骤均出现在时间线
        step_names = [str(e.data.get("name", "")) for e in events if e.type == "step_started"]
        for expected in ("库存周转概览", "库存余额分布", "工单完成概览"):
            assert any(expected in n for n in step_names), f"缺少报告步骤 {expected}: {step_names}"
        # 执行器恰好被调 3 次（每步 1 次，无失败重试）
        assert calls["n"] == 3
        # 1 plan + 3 SQL；叙述尝试会再记 1 次（FakeLLM 耗尽 → 确定性兜底）
        assert len(llm.calls) >= 1 + 3
        assert [c["model_tier"] for c in llm.calls[:4]] == ["light", "heavy", "heavy", "heavy"]
        # insight_generating.steps == 3；report 含三步名称
        ig = next(e for e in events if e.type == "insight_generating")
        assert ig.data["steps"] == 3
        report_ev = next(e for e in events if e.type == "report")
        markdown = report_ev.data["markdown"]
        for name in ("库存周转概览", "库存余额分布", "工单完成概览"):
            assert name in markdown
        done = next(e for e in events if e.type == "done")
        assert done.data["summary"]["topic"] == "inventory"
        assert done.data.get("reportId", "").startswith("rpt_")

    def test_all_steps_missing_table_yields_readable_error(self, retriever, cfg, patch_executor):
        # inventory 三步全部缺表 → 缺表分类不重试（每步 1 次执行）→ REPORT_STEPS_FAILED
        # message 携带原错误，suggestion 点名 T-015 两表
        effects = [_MISSING_TABLE_ERR, _MISSING_TABLE_ERR, _MISSING_TABLE_ERR]
        calls = patch_executor(effects)
        llm = _FakeLLM([
            _resp(PLAN_INVENTORY_REPORT_JSON),
            _resp(SQL_INV_TURNOVER),
            _resp(SQL_INV_BALANCE),
            _resp(SQL_ORDER_COMPLETION),
        ])
        events = _parse_frames(_collect(self._req(), llm, retriever, cfg))
        types = [e.type for e in events]
        assert types[-1] == "error", f"缺表时应收口为 error，实际: {types}"
        err = next(e for e in events if e.type == "error")
        assert err.data["code"] == "REPORT_STEPS_FAILED"
        assert "inventory_records" in err.data["message"] or "不存在" in err.data["message"]
        assert "T-015" in err.data["suggestion"]
        # 缺表不触发 SQL 回喂重生成：恰好 3 次执行（每步 1 次），且规划后不再调 LLM 重试 SQL
        assert calls["n"] == 3
        assert len(llm.calls) == 1 + 3  # 1 plan + 3 SQL（无重试）

    def test_partial_missing_table_still_reports(self, retriever, cfg, patch_executor):
        # 首步缺表、后续步骤成功 → 报告仍生成；失败步骤保留可读原因（不含错误码，防 ADR-3 误剔）
        patch_executor([
            _MISSING_TABLE_ERR,
            _exec_trend(),
            _exec_top(),
        ])
        # 不提供报告叙述脚本 → FakeLLM 耗尽 → 确定性兜底（数字天然可溯源）
        llm = _FakeLLM([
            _resp(PLAN_INVENTORY_REPORT_JSON),
            _resp(SQL_INV_TURNOVER),
            _resp(SQL_INV_BALANCE),
            _resp(SQL_ORDER_COMPLETION),
        ])
        events = _parse_frames(_collect(self._req(), llm, retriever, cfg))
        types = [e.type for e in events]
        assert "error" not in types, next((e.data for e in events if e.type == "error"), None)
        assert types[-1] == "done"
        # 缺表失败步骤在 step_finished 中保留完整可读错误（含表名）
        failed_detail = next(
            (e.data.get("detail", "") for e in events
             if e.type == "step_finished" and "库存周转概览" in str(e.data.get("name", ""))),
            "",
        )
        assert "inventory_records" in failed_detail or "不存在" in failed_detail
        report_ev = next(e for e in events if e.type == "report")
        markdown = report_ev.data["markdown"]
        # 报告正文：失败步骤有可读原因且不被 ADR-3 整句剔除；成功步骤仍在
        assert "库存周转概览" in markdown
        assert "未纳入报告" in markdown
        assert "库存余额分布" in markdown and "工单完成概览" in markdown

    def test_infra_error_does_not_retry_sql(self, retriever, cfg, patch_executor):
        # 连接失败：基础设施错误不触发无谓 SQL 重生成（bug-log P2 池）
        calls = patch_executor([_INFRA_ERR, _INFRA_ERR, _INFRA_ERR])
        llm = _FakeLLM([
            _resp(PLAN_INVENTORY_REPORT_JSON),
            _resp(SQL_INV_TURNOVER),
            _resp(SQL_INV_BALANCE),
            _resp(SQL_ORDER_COMPLETION),
        ])
        events = _parse_frames(_collect(self._req(), llm, retriever, cfg))
        err = next(e for e in events if e.type == "error")
        assert err.data["code"] == "REPORT_STEPS_FAILED"
        assert "基础设施" in err.data["message"] or "2003" in err.data["message"] or "Can't connect" in err.data["message"]
        assert calls["n"] == 3
        assert len(llm.calls) == 1 + 3


class TestMainFlowTableMissing:
    """主流程（非报告）缺表/基础设施错误同样可读收口，不无谓重试。"""

    def _req(self, question: str = "统计各仓库最新库存数量") -> Any:
        from app.api.routes import AnalyzeRequest

        return AnalyzeRequest(sessionId="s-tbl", messageId="m-tbl", question=question, history=[])

    def test_missing_table_main_flow_readable(self, retriever, cfg, patch_executor):
        calls = patch_executor([_MISSING_TABLE_ERR])
        plan_inv = (
            '{"intent":"query","topic":"inventory","tables":["inventory_records"],"metrics":[],'
            '"dimensions":["warehouse"],"filters":[],"time_range":{},"execution_mode":"sql",'
            '"chart_type":"bar","expected_output":"各仓库库存"}'
        )
        llm = _FakeLLM([_resp(plan_inv), _resp(SQL_INV_BALANCE)])
        events = _parse_frames(_collect(self._req(), llm, retriever, cfg))
        err = next(e for e in events if e.type == "error")
        assert err.data["code"] == "TABLE_MISSING"
        assert "inventory_records" in err.data["message"] or "不存在" in err.data["message"]
        assert "T-015" in err.data["suggestion"]
        assert calls["n"] == 1
        assert len(llm.calls) == 2  # plan + 1 次 SQL（缺表不重试）

    def test_infra_error_main_flow_readable(self, retriever, cfg, patch_executor):
        calls = patch_executor([_INFRA_ERR])
        plan_q = (
            '{"intent":"query","topic":"quality","tables":["process_output"],"metrics":["工序良率"],'
            '"dimensions":["process_name"],"filters":[],"time_range":{},"execution_mode":"sql",'
            '"chart_type":"bar","expected_output":"各工序良率"}'
        )
        llm = _FakeLLM([_resp(plan_q), _resp(SQL_TREND)])
        events = _parse_frames(_collect(self._req("统计各工序良率"), llm, retriever, cfg))
        err = next(e for e in events if e.type == "error")
        assert err.data["code"] == "INFRA_ERROR"
        assert "MySQL" in err.data["suggestion"] or "基础设施" in err.data["message"]
        assert calls["n"] == 1
        assert len(llm.calls) == 2
