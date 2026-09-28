# AI-assisted
"""T-005 mock 测试：检索器 / planner / 编排流水线 / 图表模板 / API 路由。

不依赖真实 LLM Key 与 MySQL：LLMClient.chat 用 FakeLLM 脚本化响应替代，
execute_readonly 用 monkeypatch 打桩返回固定 ExecResult（docs/03 §7：mock 事件序列先行）。
"""
from __future__ import annotations

import asyncio
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.routes import AnalyzeRequest
from app.chart.builder import build_chart_option, pick_axes, truncate_title
from app.config import Settings
from app.llm.client import LLMClient, LLMNotConfiguredError, LLMResponse
from app.orchestrator.pipeline import _auto_chart_type, run_analysis
from app.orchestrator.planner import make_plan
from app.retriever import DEFAULT_CORPUS_PATH, CorpusNotLoadedError, Retriever
from app.schemas.event import SSEEvent
from app.sqlguard.executor import ExecResult, SQLExecutionError


def _corpus_expected_counts() -> dict[str, int]:
    """动态读取 corpus.json 实际计数（BUG-014）。

    来源：T-015 数据底座补全后语料为 tables=5 / metrics=13 / examples=12；
    测试不得硬编码计数，数据组扩表后应自动跟随，避免门禁再红。
    """
    raw = json.loads(Path(DEFAULT_CORPUS_PATH).read_text(encoding="utf-8"))
    return {
        "tables": len(raw.get("tables") or []),
        "metrics": len(raw.get("metrics") or []),
        "examples": len(raw.get("examples") or []),
    }


# ---- 固定脚本（plan JSON → SQL → 结论文本）----

PLAN_JSON = (
    '{"intent":"query","topic":"quality","tables":["process_output"],"metrics":["工序良率"],'
    '"dimensions":["process_name"],"filters":[],"time_range":{},"execution_mode":"sql",'
    '"chart_type":"bar","expected_output":"各工序良率对比"}'
)

SQL_1 = (
    "SELECT process_name, ROUND(SUM(qualified_qty)/NULLIF(SUM(produced_qty),0)*100, 2) AS yield_rate "
    "FROM process_output GROUP BY process_name ORDER BY yield_rate"
)

SQL_2 = (
    "SELECT process_name, ROUND(SUM(qualified_qty)/NULLIF(SUM(produced_qty),0)*100, 2) AS yield_rate "
    "FROM process_output GROUP BY process_name"
)

CONCLUSION = (
    "各工序良率整体处于 90%~98% 区间，其中焊接工序良率最低，为 90.83%。"
    "喷涂工序良率最高，为 97.22%，与焊接相差 6.39 个百分点。"
    "口径说明：良率=合格数量/投产数量×100，先按工序汇总再相除。"
)

# T-009 修复4：规划层拒写（intent=refuse）脚本
PLAN_REFUSE_JSON = (
    '{"intent":"refuse","topic":null,"tables":[],"metrics":[],"dimensions":[],"filters":[],'
    '"time_range":{},"execution_mode":"sql","chart_type":null,"expected_output":"拒绝写操作请求"}'
)

# T-009 修复3：多系列折线（产线维度）脚本
TREND_PLAN_JSON = (
    '{"intent":"trend","topic":"production","tables":["process_output"],"metrics":["产量"],'
    '"dimensions":["production_line","production_date"],"filters":[],"time_range":{},'
    '"execution_mode":"sql","chart_type":"line","expected_output":"各产线近7天产量趋势"}'
)

TREND_SQL = (
    "SELECT production_date, production_line, SUM(produced_qty) AS produced_qty "
    "FROM process_output GROUP BY production_date, production_line ORDER BY production_date"
)

# T-009 修复2：流式结论的 3 个片段
STREAM_PIECES = [
    "各工序良率整体处于 90%~98% 区间。",
    "其中焊接工序良率最低，为 90.83%；喷涂工序最高，为 97.22%。",
    "口径说明：良率=合格数量/投产数量×100，先按工序汇总再相除。",
]


class FakeLLM:
    """脚本化 LLM：按序弹出响应并记录每次调用参数。"""

    def __init__(self, responses: list[Any], *, chat_error: Exception | None = None) -> None:
        self.responses = list(responses)
        self.chat_error = chat_error
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, *, model_tier="heavy", tools=None, response_format=None):
        self.calls.append(
            {"messages": messages, "model_tier": model_tier, "response_format": response_format}
        )
        if self.chat_error is not None:
            raise self.chat_error
        if not self.responses:
            raise AssertionError("FakeLLM 响应脚本已耗尽")
        return self.responses.pop(0)


class StreamingFakeLLM(FakeLLM):
    """带 chat_stream 的 FakeLLM：结论阶段按脚本逐片段流式产出（T-009 修复2）。"""

    def __init__(self, responses: list[Any], pieces: list[str]) -> None:
        super().__init__(responses)
        self._pieces = list(pieces)
        self.stream_calls: list[dict[str, Any]] = []

    def chat_stream(self, messages, *, model_tier="heavy"):
        self.stream_calls.append({"messages": messages, "model_tier": model_tier})
        yield from self._pieces


class EmptyStreamFakeLLM(FakeLLM):
    """chat_stream 为空流的 FakeLLM：验证回退到非流式切块路径。"""

    def __init__(self, responses: list[Any]) -> None:
        super().__init__(responses)
        self.stream_calls = 0

    def chat_stream(self, messages, *, model_tier="heavy"):
        self.stream_calls += 1
        yield from ()


def _resp(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        provider="fake",
    )


def _exec_result(rowcount: int = 5) -> ExecResult:
    """5 工序良率 2 列（Decimal 模拟 pymysql 返回，验证归一化）。"""
    data = [("注塑", "97.06"), ("焊接", "90.83"), ("装配", "96.36"), ("喷涂", "97.22"), ("包装", "96.53")]
    rows = [{"process_name": name, "yield_rate": Decimal(rate)} for name, rate in data[:rowcount]]
    return ExecResult(
        columns=["process_name", "yield_rate"],
        rows=rows,
        rowcount=rowcount,
        elapsed_ms=12.3,
        truncated=False,
    )


@pytest.fixture
def retriever() -> Retriever:
    return Retriever(DEFAULT_CORPUS_PATH)


@pytest.fixture
def cfg() -> Settings:
    return Settings(sql_max_limit=500)


@pytest.fixture
def patch_executor(monkeypatch):
    """打桩 app.orchestrator.pipeline.execute_readonly：effects 逐次生效。"""

    def _install(effects: list[Any]) -> dict[str, int]:
        calls = {"n": 0}

        def _fake(sql, session_cfg, **kwargs):
            index = calls["n"]
            calls["n"] += 1
            effect = effects[index] if index < len(effects) else effects[-1]
            if isinstance(effect, Exception):
                raise effect
            assert sql  # 编排器必须传已校验 SQL
            return effect

        monkeypatch.setattr("app.orchestrator.pipeline.execute_readonly", _fake)
        return calls

    return _install


def _collect_frames(req, llm, retriever_, cfg_) -> list[str]:
    async def _run() -> list[str]:
        return [frame async for frame in run_analysis(req, llm, retriever_, cfg_)]

    return asyncio.run(_run())


def _parse(frames: list[str]) -> list[SSEEvent]:
    events: list[SSEEvent] = []
    for frame in frames:
        assert frame.endswith("\n\n"), f"SSE 帧必须以空行结尾: {frame!r}"
        body = frame[:-2]
        head, sep, data = body.partition("\ndata: ")
        assert head.startswith("event: ") and sep, f"SSE 帧格式非法: {frame!r}"
        events.append(SSEEvent(type=head[len("event: "):], data=json.loads(data)))
    return events


def _make_req(question: str = "请分析各工序的良率。") -> AnalyzeRequest:
    return AnalyzeRequest(sessionId="s-1", messageId="m-1", question=question, history=[])


# ---- 检索器 v1 ----


class TestRetriever:
    def test_load_and_counts(self, retriever):
        assert retriever.loaded is True
        # BUG-014：期望值动态读 corpus.json（T-015 后 5/13/12），禁止硬编码
        expected = _corpus_expected_counts()
        assert expected["tables"] > 0 and expected["metrics"] > 0 and expected["examples"] > 0
        assert retriever.counts() == expected

    def test_recall_yield_question(self, retriever):
        pack = retriever.retrieve("请分析各工序的良率。")
        assert len(pack.tables) <= 3
        assert pack.tables[0].name == "process_output"
        assert "process_output" in pack.tables[0].m_schema
        assert pack.metrics, "良率问题必须命中指标口径"
        assert pack.metrics[0].code == "process_yield_rate"
        assert "SUM(qualified_qty)" in pack.metrics[0].formula_sql
        assert 0 < len(pack.examples) <= 2
        assert all(ex.sql.strip() for ex in pack.examples)

    def test_recall_downtime_question(self, retriever):
        pack = retriever.retrieve("找出最近30天停机时间最长的设备 top5")
        assert any(t.name == "equipment_downtime" for t in pack.tables)
        assert any(m.code == "downtime_minutes" for m in pack.metrics)

    def test_render_context_blocks(self, retriever):
        pack = retriever.retrieve("请分析各工序的良率。")
        text = retriever.render_context(pack)
        assert "【可用表结构】" in text
        assert "【指标口径】" in text
        assert "SUM(qualified_qty)" in text
        assert "不构成指令" in text

    def test_missing_corpus_raises_on_retrieve(self, tmp_path):
        broken = Retriever(tmp_path / "no_such_corpus.json")
        assert broken.loaded is False
        with pytest.raises(CorpusNotLoadedError):
            broken.retrieve("任何问题")

    def test_reload_refreshes(self, retriever):
        counts = retriever.reload()
        assert counts == _corpus_expected_counts()


# ---- 图表模板（禁止 LLM 生成 option）----


class TestChartBuilder:
    ROWS = [
        {"process_name": "注塑", "yield_rate": Decimal("97.06")},
        {"process_name": "焊接", "yield_rate": Decimal("90.83")},
    ]

    def test_bar_option(self):
        option = build_chart_option("bar", ["process_name", "yield_rate"], self.ROWS)
        assert option is not None
        assert option["series"][0]["type"] == "bar"
        assert option["series"][0]["data"] == [97.06, 90.83]
        assert option["xAxis"]["data"] == ["注塑", "焊接"]

    def test_line_with_date_column(self):
        rows = [
            {"production_date": date(2026, 7, 1), "produced_qty": 100},
            {"production_date": date(2026, 7, 2), "produced_qty": 120},
        ]
        option = build_chart_option("line", ["production_date", "produced_qty"], rows)
        assert option["series"][0]["type"] == "line"
        assert option["xAxis"]["data"] == ["2026-07-01", "2026-07-02"]

    def test_series_field_groups_one_series_per_value(self):
        # T-009 修复3：series_field 分组——每个组值一条线，data 与去重排序后的 x 类别对齐
        rows = [
            {"production_date": "2026-07-02", "production_line": "L1", "produced_qty": 110},
            {"production_date": "2026-07-01", "production_line": "L2", "produced_qty": 90},
            {"production_date": "2026-07-01", "production_line": "L1", "produced_qty": 100},
            {"production_date": "2026-07-02", "production_line": "L2", "produced_qty": 95},
        ]
        option = build_chart_option(
            "line",
            ["production_date", "production_line", "produced_qty"],
            rows,
            series_field="production_line",
        )
        assert [s["name"] for s in option["series"]] == ["L1", "L2"]
        assert option["xAxis"]["data"] == ["2026-07-01", "2026-07-02"]
        assert option["series"][0]["data"] == [100, 110]
        assert option["series"][1]["data"] == [90, 95]

    def test_series_field_missing_column_falls_back(self):
        # series_field 不在 columns / 等于 x 轴列 → 回退"每列一条线"
        rows = [{"production_date": "2026-07-01", "produced_qty": 1}]
        fallback = build_chart_option(
            "line", ["production_date", "produced_qty"], rows, series_field="no_such_col"
        )
        assert len(fallback["series"]) == 1 and fallback["series"][0]["name"] == "produced_qty"
        same_as_x = build_chart_option(
            "line", ["production_date", "produced_qty"], rows, series_field="production_date"
        )
        assert len(same_as_x["series"]) == 1

    def test_series_field_ignored_for_pie_and_scatter(self):
        option = build_chart_option(
            "pie", ["process_name", "yield_rate"], self.ROWS, series_field="process_name"
        )
        assert option["series"][0]["type"] == "pie"

    def test_bar_sparse_series_falls_back_single_series(self):
        # BUG-018 / T-028：columns 含 product_id, product_name, avg_stock；
        # series_field=product_name → 每系列仅 1 非空点、系列数≈类目数 → 回退单系列，
        # data 与 xAxis 对齐（不再按产品名拆成一堆空系列）
        rows = [
            {"product_id": "P001", "product_name": "产品A", "avg_stock": 120},
            {"product_id": "P002", "product_name": "产品B", "avg_stock": 80},
            {"product_id": "P003", "product_name": "产品C", "avg_stock": 200},
            {"product_id": "P004", "product_name": "产品D", "avg_stock": 50},
            {"product_id": "P005", "product_name": "产品E", "avg_stock": 160},
        ]
        columns = ["product_id", "product_name", "avg_stock"]
        option = build_chart_option("bar", columns, rows, series_field="product_name")
        assert option is not None
        assert len(option["series"]) == 1, "稀疏分组应回退单系列柱图"
        assert option["series"][0]["type"] == "bar"
        assert option["series"][0]["name"] == "avg_stock"
        assert option["xAxis"]["data"] == ["P001", "P002", "P003", "P004", "P005"]
        assert option["series"][0]["data"] == [120, 80, 200, 50, 160]
        assert len(option["series"][0]["data"]) == len(option["xAxis"]["data"])
        assert "grid" in option, "option 必须补 grid 留白"

    def test_bar_dense_series_still_grouped(self):
        # 真正的多系列柱图（产线×工序，每系列多点）不应被稀疏回退误伤
        rows = [
            {"process_name": "注塑", "production_line": "L1", "produced_qty": 100},
            {"process_name": "焊接", "production_line": "L1", "produced_qty": 110},
            {"process_name": "装配", "production_line": "L1", "produced_qty": 90},
            {"process_name": "注塑", "production_line": "L2", "produced_qty": 80},
            {"process_name": "焊接", "production_line": "L2", "produced_qty": 85},
            {"process_name": "装配", "production_line": "L2", "produced_qty": 70},
        ]
        option = build_chart_option(
            "bar",
            ["process_name", "production_line", "produced_qty"],
            rows,
            series_field="production_line",
        )
        assert option is not None
        assert [s["name"] for s in option["series"]] == ["L1", "L2"]
        assert option["series"][0]["data"] == [100, 110, 90]
        assert option["series"][1]["data"] == [80, 85, 70]
        assert "grid" in option

    def test_line_bar_pie_options_have_grid(self):
        # BUG-018 / T-028：所有 line/bar/pie option 补 grid（top 留 title+legend，bottom 留轴名）
        bar = build_chart_option("bar", ["process_name", "yield_rate"], self.ROWS)
        assert "grid" in bar and bar["grid"]["top"] >= 50 and bar["grid"]["bottom"] >= 40
        assert bar["grid"].get("containLabel") is True

        line_rows = [
            {"production_date": date(2026, 7, 1), "production_line": "L1", "produced_qty": 100},
            {"production_date": date(2026, 7, 1), "production_line": "L2", "produced_qty": 90},
            {"production_date": date(2026, 7, 2), "production_line": "L1", "produced_qty": 110},
            {"production_date": date(2026, 7, 2), "production_line": "L2", "produced_qty": 95},
        ]
        line = build_chart_option(
            "line",
            ["production_date", "production_line", "produced_qty"],
            line_rows,
            series_field="production_line",
        )
        assert "grid" in line
        assert line["grid"]["top"] >= 80, "带 legend 时 top 应容纳 title+legend"

        pie = build_chart_option("pie", ["process_name", "yield_rate"], self.ROWS)
        assert "grid" in pie and pie["grid"]["top"] >= 50

    def test_pie_and_scatter(self):
        pie = build_chart_option("pie", ["process_name", "yield_rate"], self.ROWS)
        assert pie["series"][0]["type"] == "pie"
        assert pie["series"][0]["data"][0] == {"name": "注塑", "value": 97.06}

        rows = [{"x_qty": 1, "y_rate": 2.5}, {"x_qty": 3, "y_rate": 4.5}]
        scatter = build_chart_option("scatter", ["x_qty", "y_rate"], rows)
        assert scatter["series"][0]["type"] == "scatter"
        assert scatter["series"][0]["data"] == [[1, 2.5], [3, 4.5]]

    def test_unsupported_or_non_numeric_returns_none(self):
        assert build_chart_option("table", ["process_name", "yield_rate"], self.ROWS) is None
        assert build_chart_option("bar", ["a", "b"], [{"a": "x", "b": "y"}, {"a": "z", "b": "w"}]) is None
        assert build_chart_option("bar", ["process_name"], [{"process_name": "注塑"}]) is None
        assert build_chart_option("bar", ["yield_rate"], []) is None

    def test_pick_axes_and_title_truncate(self):
        x, ys = pick_axes("bar", ["process_name", "yield_rate"], self.ROWS)
        assert (x, ys) == ("process_name", ["yield_rate"])
        assert truncate_title("一" * 50) == "一" * 29 + "…"
        assert truncate_title("各工序良率对比") == "各工序良率对比"
        assert truncate_title("") == "分析图表"

    def test_auto_chart_type(self):
        assert _auto_chart_type(["production_date", "produced_qty"], [{"production_date": "2026-07-01", "produced_qty": 1}]) == "line"
        assert _auto_chart_type(["process_name", "yield_rate"], self.ROWS) == "bar"


# ---- planner ----


class TestPlanner:
    def test_parse_plan_light_tier_json_object(self):
        llm = FakeLLM([_resp(PLAN_JSON)])
        plan = make_plan(llm, "请分析各工序的良率。", history=[])
        assert plan.intent == "query"
        assert plan.topic == "quality"
        assert plan.execution_mode == "sql"
        assert plan.chart_type == "bar"
        assert plan.expected_output == "各工序良率对比"
        assert llm.calls[0]["model_tier"] == "light"
        assert llm.calls[0]["response_format"] == {"type": "json_object"}
        assert llm.calls[0]["messages"][0]["role"] == "system"

    def test_retry_once_then_default_plan(self):
        llm = FakeLLM([_resp("这不是JSON"), _resp("{{{{")])
        plan = make_plan(llm, "各工序的良率如何？")
        assert isinstance(plan.expected_output, str)
        assert plan.execution_mode == "sql"
        assert plan.chart_type is None
        assert plan.expected_output == "各工序的良率如何？"
        assert len(llm.calls) == 2, "解析失败应恰好重试 1 次"

    def test_retry_recovers_with_valid_json(self):
        llm = FakeLLM([_resp("前导噪声"), _resp(f"```json\n{PLAN_JSON}\n```")])
        plan = make_plan(llm, "请分析各工序的良率。")
        assert plan.topic == "quality"
        assert len(llm.calls) == 2

    def test_llm_transport_error_propagates(self):
        llm = FakeLLM([], chat_error=LLMNotConfiguredError("未配置任何 LLM API Key"))
        with pytest.raises(LLMNotConfiguredError):
            make_plan(llm, "问题")


# ---- 编排流水线（mock 全链路）----


class TestPipelineHappyPath:
    def test_event_sequence_and_frames(self, retriever, cfg, patch_executor):
        patch_executor([_exec_result()])
        llm = FakeLLM([_resp(PLAN_JSON), _resp(SQL_1), _resp(CONCLUSION)])
        frames = _collect_frames(_make_req(), llm, retriever, cfg)
        events = _parse(frames)

        types = [e.type for e in events]
        core = [t for t in types if t != "text_delta"]
        # T-009 修复1：全程补 step_started/step_finished 步骤时间线事件
        assert core == [
            "task_started",
            "step_started", "step_finished",  # 意图理解
            "plan_ready",
            "step_started", "step_finished",  # 资源定位
            "step_started", "sql_generated", "step_finished",  # 生成SQL
            "step_started", "sql_validated", "step_finished",  # 安全校验
            "step_started", "sql_executing", "sql_completed", "step_finished",  # 执行
            "table",
            "step_started", "chart_building", "chart", "step_finished",  # 生成图表
            "step_started", "step_finished",  # 生成结论
            "done",
        ]
        deltas = [e for e in events if e.type == "text_delta"]
        assert 3 <= len(deltas) <= 5, "非流式结论应切 3-5 段"
        assert all(types.index("text_delta") > types.index("chart") for _ in [0])

        # 步骤时间线覆盖六类必备阶段 + 生成图表；started/finished 成对且 stepId 递增
        steps = [e for e in events if e.type in ("step_started", "step_finished")]
        names = [e.data["name"] for e in steps]
        for name in ("意图理解", "资源定位", "生成SQL", "安全校验", "执行", "生成图表", "生成结论"):
            assert names.count(name) == 2, f"步骤 {name} 应有 started/finished 各一次"
        started_ids = [e.data["stepId"] for e in steps if e.type == "step_started"]
        finished_ids = [e.data["stepId"] for e in steps if e.type == "step_finished"]
        assert started_ids == finished_ids, "同一步骤的 started/finished stepId 必须配对"
        assert started_ids == sorted(started_ids, key=int), "stepId 应按短序号递增"
        assert all(e.data.get("detail") for e in steps), "step 事件必须携带 detail"

        # plan_ready 载荷 = AnalysisPlan.model_dump()
        plan_ready = next(e for e in events if e.type == "plan_ready")
        assert plan_ready.data["intent"] == "query"
        assert plan_ready.data["topic"] == "quality"
        assert plan_ready.data["execution_mode"] == "sql"
        assert plan_ready.data["chart_type"] == "bar"

        # SQL 链路载荷
        generated = next(e for e in events if e.type == "sql_generated")
        assert "yield_rate" in generated.data["sql"]
        validated = next(e for e in events if e.type == "sql_validated")
        assert validated.data["valid"] is True
        assert validated.data["sql"].upper().endswith("LIMIT 500"), "校验器应补 LIMIT"
        completed = next(e for e in events if e.type == "sql_completed")
        assert completed.data["rowCount"] == 5
        assert isinstance(completed.data["elapsedMs"], int)

        # LLM 分层：light 规划 + heavy 生成 SQL + heavy 结论
        assert [c["model_tier"] for c in llm.calls] == ["light", "heavy", "heavy"]

    def test_done_standard_result_object(self, retriever, cfg, patch_executor):
        patch_executor([_exec_result()])
        llm = FakeLLM([_resp(PLAN_JSON), _resp(SQL_1), _resp(CONCLUSION)])
        events = _parse(_collect_frames(_make_req(), llm, retriever, cfg))

        done = next(e for e in events if e.type == "done")
        data = done.data
        for key in ("columns", "rows", "summary", "chart", "insights", "warnings", "sql", "execution_info"):
            assert key in data, f"标准结果对象缺少 {key}"
        assert data["columns"] == ["process_name", "yield_rate"]
        assert len(data["rows"]) == 5
        assert data["rows"][0]["yield_rate"] == pytest.approx(97.06), "Decimal 应归一化为 float"
        assert "yield_rate" in data["sql"]
        assert data["insights"], "结论应拆入 insights"
        assert any("口径说明" in s for s in data["insights"])
        info = data["execution_info"]
        assert info["rowCount"] == 5 and info["truncated"] is False
        assert "mes_demo" in info["dataSource"]
        assert {"durationMs", "rowCount", "dataSource", "truncated"} <= set(info)
        assert data["tokensCost"]["total_tokens"] == 300
        assert isinstance(data["durationMs"], int)

        chart = data["chart"]
        assert chart["type"] in ("bar", "line")
        assert chart["x"] == "process_name"
        assert chart["y"] == ["yield_rate"]

    def test_chart_event_payload(self, retriever, cfg, patch_executor):
        patch_executor([_exec_result()])
        llm = FakeLLM([_resp(PLAN_JSON), _resp(SQL_1), _resp(CONCLUSION)])
        events = _parse(_collect_frames(_make_req(), llm, retriever, cfg))

        chart = next(e for e in events if e.type == "chart")
        assert isinstance(chart.data["option"], dict), "chart 事件必须携带 ECharts option"
        assert chart.data["option"]["series"][0]["type"] == "bar"
        assert chart.data["type"] == "bar"
        assert chart.data["option"]["title"]["text"] == "各工序良率对比", "标题取 expected_output"
        building = next(e for e in events if e.type == "chart_building")
        assert building.data["type"] == "bar"

    def test_line_chart_from_date_result(self, retriever, cfg, patch_executor):
        patch_executor([
            ExecResult(
                columns=["production_date", "produced_qty"],
                rows=[
                    {"production_date": date(2026, 7, 1), "produced_qty": 100},
                    {"production_date": date(2026, 7, 2), "produced_qty": 120},
                ],
                rowcount=2,
                elapsed_ms=5.0,
                truncated=False,
            )
        ])
        trend_plan = PLAN_JSON.replace('"chart_type":"bar"', '"chart_type":"line"').replace(
            '"expected_output":"各工序良率对比"', '"expected_output":"近7天产量趋势"'
        )
        llm = FakeLLM([_resp(trend_plan), _resp("SELECT production_date, SUM(produced_qty) AS produced_qty FROM process_output GROUP BY production_date"), _resp(CONCLUSION)])
        events = _parse(_collect_frames(_make_req(), llm, retriever, cfg))
        chart = next(e for e in events if e.type == "chart")
        assert chart.data["type"] == "line"
        assert chart.data["option"]["series"][0]["type"] == "line"


class TestPipelineSelfRepair:
    def test_execution_error_triggers_regeneration(self, retriever, cfg, patch_executor):
        patch_executor([
            SQLExecutionError('[执行失败] OperationalError: (1054, "Unknown column \'bad_col\'")'),
            _exec_result(),
        ])
        llm = FakeLLM([_resp(PLAN_JSON), _resp(SQL_1), _resp(SQL_2), _resp(CONCLUSION)])
        events = _parse(_collect_frames(_make_req(), llm, retriever, cfg))

        generated = [e for e in events if e.type == "sql_generated"]
        assert len(generated) == 2, "执行失败重生成后 sql_generated 应出现两次"
        completed = [e for e in events if e.type == "sql_completed"]
        assert len(completed) == 1
        done = next(e for e in events if e.type == "done")
        assert done.data["execution_info"]["rowCount"] == 5
        # 报错信息必须回喂给 LLM
        second_call_messages = llm.calls[2]["messages"]
        assert any("执行失败" in m["content"] for m in second_call_messages if m["role"] == "user")

    def test_validation_error_triggers_regeneration(self, retriever, cfg, patch_executor):
        # T-009 修复4：DELETE 属[禁止语句]走只读拒绝路径，不再触发重生成；
        # 本用例改用非禁止类校验失败（多语句）验证自修复循环仍然生效
        patch_executor([_exec_result()])
        llm = FakeLLM([_resp(PLAN_JSON), _resp("SELECT 1; SELECT 2"), _resp(SQL_1), _resp(CONCLUSION)])
        events = _parse(_collect_frames(_make_req(), llm, retriever, cfg))

        generated = [e for e in events if e.type == "sql_generated"]
        assert len(generated) == 2
        invalid = [e for e in events if e.type == "sql_validated" and e.data["valid"] is False]
        assert len(invalid) == 1 and "多语句" in invalid[0].data["message"]
        assert not any(e.type == "sql_executing" for e in events[: events.index(invalid[0])])
        assert any(e.type == "done" for e in events)

    def test_persistent_failure_emits_error(self, retriever, cfg, patch_executor):
        patch_executor([_exec_result()])
        bad_sqls = [_resp("SELECT 1; SELECT 2")] * 3
        llm = FakeLLM([_resp(PLAN_JSON), *bad_sqls])
        events = _parse(_collect_frames(_make_req(), llm, retriever, cfg))

        error = next(e for e in events if e.type == "error")
        assert error.data["code"] == "SQL_VALIDATE_FAILED"
        assert error.data["message"] and error.data["suggestion"]
        assert not any(e.type == "done" for e in events)


class TestPipelineStreamingConclusion:
    """T-009 修复2：结论真流式（chat_stream 逐片段 text_delta）与空流回退。"""

    def test_streamed_pieces_emitted_as_deltas(self, retriever, cfg, patch_executor):
        patch_executor([_exec_result()])
        llm = StreamingFakeLLM([_resp(PLAN_JSON), _resp(SQL_1)], STREAM_PIECES)
        events = _parse(_collect_frames(_make_req(), llm, retriever, cfg))

        deltas = [e for e in events if e.type == "text_delta"]
        assert len(deltas) >= 3
        assert [d.data["delta"] for d in deltas] == STREAM_PIECES
        assert "".join(d.data["delta"] for d in deltas) == "".join(STREAM_PIECES)
        # 流式路径下结论不再回调阻塞 chat()：chat 仅规划(light)+生成SQL(heavy) 两次
        assert [c["model_tier"] for c in llm.calls] == ["light", "heavy"]
        assert len(llm.stream_calls) == 1 and llm.stream_calls[0]["model_tier"] == "heavy"
        # done 汇总全文；结论步骤事件包裹流式片段
        done = next(e for e in events if e.type == "done")
        assert done.data["summary"]["conclusion"] == "".join(STREAM_PIECES)
        types = [e.type for e in events]
        conclude_started_pos = next(
            i for i, e in enumerate(events)
            if e.type == "step_started" and e.data["name"] == "生成结论"
        )
        conclude_finished_pos = next(
            i for i, e in enumerate(events)
            if e.type == "step_finished" and e.data["name"] == "生成结论"
        )
        first_delta_pos = types.index("text_delta")
        assert conclude_started_pos < first_delta_pos < conclude_finished_pos, \
            "text_delta 应夹在生成结论的 step_started/step_finished 之间"

    def test_empty_stream_falls_back_to_chunked(self, retriever, cfg, patch_executor):
        patch_executor([_exec_result()])
        llm = EmptyStreamFakeLLM([_resp(PLAN_JSON), _resp(SQL_1), _resp(CONCLUSION)])
        events = _parse(_collect_frames(_make_req(), llm, retriever, cfg))

        deltas = [e for e in events if e.type == "text_delta"]
        assert 3 <= len(deltas) <= 5, "空流应回退 _chunk_text 切 3-5 段"
        assert "".join(d.data["delta"] for d in deltas) == CONCLUSION
        assert llm.stream_calls == 1
        assert len(llm.calls) == 3, "回退路径应调用一次阻塞 chat() 生成结论"


class TestPipelineMultiSeriesChart:
    """T-009 修复3：dimensions[0] 作 series_field，多产线折线不串成一条线。"""

    def test_line_grouped_by_production_line(self, retriever, cfg, patch_executor):
        patch_executor([
            ExecResult(
                columns=["production_date", "production_line", "produced_qty"],
                rows=[
                    {"production_date": date(2026, 7, 1), "production_line": "L1", "produced_qty": 100},
                    {"production_date": date(2026, 7, 1), "production_line": "L2", "produced_qty": 90},
                    {"production_date": date(2026, 7, 1), "production_line": "L3", "produced_qty": 80},
                    {"production_date": date(2026, 7, 2), "production_line": "L1", "produced_qty": 110},
                    {"production_date": date(2026, 7, 2), "production_line": "L2", "produced_qty": 95},
                    {"production_date": date(2026, 7, 2), "production_line": "L3", "produced_qty": 85},
                    {"production_date": date(2026, 7, 3), "production_line": "L1", "produced_qty": 120},
                    {"production_date": date(2026, 7, 3), "production_line": "L2", "produced_qty": 100},
                    {"production_date": date(2026, 7, 3), "production_line": "L3", "produced_qty": 70},
                ],
                rowcount=9,
                elapsed_ms=8.0,
                truncated=False,
            )
        ])
        llm = FakeLLM([_resp(TREND_PLAN_JSON), _resp(TREND_SQL), _resp(CONCLUSION)])
        events = _parse(_collect_frames(_make_req("统计每条产线最近 7 天的产量趋势"), llm, retriever, cfg))

        chart = next(e for e in events if e.type == "chart")
        option = chart.data["option"]
        assert len(option["series"]) == 3, "L1/L2/L3 应各成一条线"
        assert [s["name"] for s in option["series"]] == ["L1", "L2", "L3"]
        assert option["xAxis"]["data"] == ["2026-07-01", "2026-07-02", "2026-07-03"]
        for series in option["series"]:
            assert series["type"] == "line"
            assert len(series["data"]) == 3, "每条线 data 长度须与 x 类别数对齐"
        assert option["series"][0]["data"] == [100, 110, 120]
        assert option["series"][1]["data"] == [90, 95, 100]
        assert option["series"][2]["data"] == [80, 85, 70]
        # ChartSpec 骨架与 option 一致
        assert chart.data["type"] == "line"
        assert chart.data["x"] == "production_date"
        assert chart.data["series"] == option["series"]
        assert "grid" in option, "多系列 line option 应带 grid 留白"

    def test_bar_sparse_product_name_series_falls_back(self, retriever, cfg, patch_executor):
        """BUG-018 / T-028：x=product_id, series_field=product_name（一行一品）→ 单系列柱图。

        _pick_series_field 会选中 dimensions[0]=product_name，但 builder 检测到
        「系列数≈类目数且每系列仅 1 非空点」后回退单系列，data 与 xAxis 对齐。
        """
        STOCK_PLAN_JSON = (
            '{"intent":"query","topic":"inventory","tables":["inventory_records"],"metrics":["库存"],'
            '"dimensions":["product_name"],"filters":[],"time_range":{},"execution_mode":"sql",'
            '"chart_type":"bar","expected_output":"哪些物料库存呆滞"}'
        )
        STOCK_SQL = (
            "SELECT product_id, product_name, AVG(stock_qty) AS avg_stock "
            "FROM inventory_records GROUP BY product_id, product_name ORDER BY avg_stock DESC"
        )
        stock_rows = [
            {"product_id": "P001", "product_name": "物料A", "avg_stock": 120},
            {"product_id": "P002", "product_name": "物料B", "avg_stock": 80},
            {"product_id": "P003", "product_name": "物料C", "avg_stock": 200},
            {"product_id": "P004", "product_name": "物料D", "avg_stock": 50},
            {"product_id": "P005", "product_name": "物料E", "avg_stock": 160},
        ]
        patch_executor([
            ExecResult(
                columns=["product_id", "product_name", "avg_stock"],
                rows=stock_rows,
                rowcount=5,
                elapsed_ms=6.0,
                truncated=False,
            )
        ])
        llm = FakeLLM([_resp(STOCK_PLAN_JSON), _resp(STOCK_SQL), _resp("物料C库存最高。")])
        events = _parse(_collect_frames(_make_req("哪些物料库存呆滞"), llm, retriever, cfg))

        chart = next(e for e in events if e.type == "chart")
        option = chart.data["option"]
        assert chart.data["type"] == "bar"
        assert len(option["series"]) == 1, "稀疏 bar 分组应回退单系列"
        assert option["series"][0]["type"] == "bar"
        assert option["xAxis"]["data"] == ["P001", "P002", "P003", "P004", "P005"]
        assert option["series"][0]["data"] == [120, 80, 200, 50, 160]
        assert "grid" in option and option["grid"]["bottom"] >= 40
        assert len(option["series"][0]["data"]) == len(option["xAxis"]["data"])


class TestPipelineReadOnlyRefusal:
    """T-009 修复4：双层只读拒绝（规划层 intent=refuse / 校验层禁止语句）。"""

    def test_plan_refuse_skips_sql_chain(self, retriever, cfg):
        llm = FakeLLM([_resp(PLAN_REFUSE_JSON)])
        events = _parse(_collect_frames(_make_req("删除所有质量检验数据"), llm, retriever, cfg))

        types = [e.type for e in events]
        assert types == [
            "task_started",
            "step_started", "step_finished",  # 意图理解
            "plan_ready",
            "step_started", "step_finished",  # 生成结论（拒绝说明）
            "text_delta",
            "done",
        ]
        forbidden = ("sql_generated", "sql_validated", "sql_executing", "sql_completed", "table",
                     "chart_building", "chart", "clarify")
        assert not any(t in types for t in forbidden), "拒绝路径不得产生 SQL/表格/图表事件"
        delta = next(e for e in events if e.type == "text_delta")
        assert "只读" in delta.data["delta"]
        done = next(e for e in events if e.type == "done")
        assert done.data["insights"] and "只读" in done.data["insights"][0]
        assert done.data["columns"] == [] and done.data["rows"] == []
        assert done.data["execution_info"]["dataSource"] == "refused"
        assert done.data["execution_info"]["durationMs"] == 0
        assert len(llm.calls) == 1, "拒绝后不应再调用生成/结论 LLM"

    def test_forbidden_sql_goes_refusal_without_repair(self, retriever, cfg, patch_executor):
        patch_executor([])  # 执行器不应被调用（effects 为空，误调用即 IndexError）
        llm = FakeLLM([_resp(PLAN_JSON), _resp("DELETE FROM process_output")])
        events = _parse(_collect_frames(_make_req("删除所有质量检验数据"), llm, retriever, cfg))

        generated = [e for e in events if e.type == "sql_generated"]
        assert len(generated) == 1, "禁止语句不得触发重生成（sql_generated 只出现一次）"
        invalid = [e for e in events if e.type == "sql_validated" and e.data["valid"] is False]
        assert len(invalid) == 1 and "禁止语句" in invalid[0].data["message"]
        assert not any(
            e.type in ("sql_executing", "sql_completed", "table", "chart", "chart_building")
            for e in events
        )
        delta = next(e for e in events if e.type == "text_delta")
        assert "只读" in delta.data["delta"]
        done = next(e for e in events if e.type == "done")
        assert done.data["insights"] and "只读" in done.data["insights"][0]
        assert len(llm.calls) == 2, "拒绝后不应再回喂重生成"
        # 安全校验失败也应有 step_finished（失败原因）
        validate_finished = [
            e for e in events if e.type == "step_finished" and e.data["name"] == "安全校验"
        ]
        assert validate_finished and "校验未通过" in validate_finished[0].data["detail"]


class TestPipelineEdgeCases:
    def test_empty_result_emits_clarify(self, retriever, cfg, patch_executor):
        patch_executor([ExecResult(columns=["process_name"], rows=[], rowcount=0, elapsed_ms=1.0, truncated=False)])
        llm = FakeLLM([_resp(PLAN_JSON), _resp(SQL_1)])
        events = _parse(_collect_frames(_make_req(), llm, retriever, cfg))

        clarify = next(e for e in events if e.type == "clarify")
        assert clarify.data["options"]
        # T-029a：空结果 clarify 保留 SQL 卡与口径说明，便于诊断
        assert clarify.data.get("sql") and "process_output" in clarify.data["sql"]
        assert "已执行 SQL" in clarify.data["question"]
        assert "口径说明" in clarify.data["question"]
        assert isinstance(clarify.data.get("diagnosis"), dict)
        done = next(e for e in events if e.type == "done")
        assert done.data["rows"] == []
        assert done.data.get("sql") and "process_output" in done.data["sql"]
        assert not any(e.type in ("chart", "text_delta") for e in events)
        assert len(llm.calls) == 2, "空结果不应再调结论 LLM"

    def test_empty_result_invented_having_retries_ranking_sql(self, retriever, cfg, patch_executor):
        """T-029a / BUG-025：臆造 HAVING 致 0 行 → 纠正为相对排名口径重生成一次。"""
        from app.orchestrator.pipeline import (
            _is_stagnant_question,
            _sql_has_invented_having,
            _stagnant_sql_extra,
        )

        bad_sql = (
            "SELECT product_id, product_name, ROUND(AVG(inventory_qty),0) AS avg_stock, "
            "ROUND(AVG(outbound_qty),1) AS avg_outbound FROM inventory_records "
            "WHERE record_date >= DATE_SUB((SELECT MAX(record_date) FROM inventory_records), INTERVAL '59' DAY) "
            "GROUP BY product_id, product_name HAVING avg_outbound < 10 "
            "ORDER BY avg_stock DESC, avg_outbound ASC LIMIT 10"
        )
        good_sql = (
            "SELECT product_id, product_name, ROUND(AVG(inventory_qty),0) AS avg_stock, "
            "ROUND(AVG(outbound_qty),1) AS avg_outbound FROM inventory_records "
            "WHERE record_date >= DATE_SUB((SELECT MAX(record_date) FROM inventory_records), INTERVAL '59' DAY) "
            "GROUP BY product_id, product_name ORDER BY avg_stock DESC, avg_outbound ASC LIMIT 10"
        )
        assert _sql_has_invented_having(bad_sql, "哪些物料库存呆滞") is True
        assert _sql_has_invented_having(good_sql, "哪些物料库存呆滞") is False
        # 用户明确给出阈值时不应判定为臆造
        assert _sql_has_invented_having(bad_sql, "找出出库量低于10的产品") is False
        assert _is_stagnant_question("哪些物料库存呆滞", None) is True
        assert "MAX(record_date)" in _stagnant_sql_extra()
        assert "禁止臆造" in _stagnant_sql_extra()

        stock_plan = (
            '{"intent":"query","topic":"inventory","tables":["inventory_records"],"metrics":["日均期末库存"],'
            '"dimensions":["product_name"],"filters":[],"time_range":{},"execution_mode":"sql",'
            '"chart_type":"bar","expected_output":"库存持续走高而出货稀少的物料"}'
        )
        good_rows = [
            {"product_id": "P-1003", "product_name": "车门内板", "avg_stock": 2430.0, "avg_outbound": 13.5},
            {"product_id": "P-1002", "product_name": "前保险杠", "avg_stock": 2536.0, "avg_outbound": 148.8},
        ]
        patch_executor([
            ExecResult(columns=["product_id", "product_name", "avg_stock", "avg_outbound"],
                       rows=[], rowcount=0, elapsed_ms=1.0, truncated=False),
            ExecResult(columns=["product_id", "product_name", "avg_stock", "avg_outbound"],
                       rows=good_rows, rowcount=2, elapsed_ms=2.0, truncated=False),
        ])
        llm = FakeLLM([
            _resp(stock_plan),
            _resp(bad_sql),
            _resp(good_sql),  # 纠正轮
            _resp("车门内板库存高且出库极低，存在呆滞迹象。口径说明：近60天锚 MAX(record_date)。"),
        ])
        events = _parse(_collect_frames(_make_req("哪些物料库存呆滞"), llm, retriever, cfg))
        sqls = [e.data["sql"] for e in events if e.type == "sql_generated"]
        assert len(sqls) == 2, "应先出臆造 HAVING SQL，再纠正重生成一次"
        assert "HAVING" in sqls[0]
        assert "HAVING" not in sqls[1]
        assert any(e.type == "table" and e.data.get("total") == 2 for e in events)
        assert not any(e.type == "clarify" for e in events), "纠正后非空不应 clarify"
        done = next(e for e in events if e.type == "done")
        assert done.data["rows"]
        # 纠正指令须带入用户消息
        retry_user = llm.calls[2]["messages"][-1]["content"]
        assert "0 行" in retry_user and "HAVING" in retry_user and "MAX(record_date)" in retry_user

    def test_stagnant_plan_prompt_guides_ranking_not_having(self):
        """T-029a：SQL/规划提示词固化呆滞口径与 MAX(record_date) 锚点。"""
        from app.llm import prompts as prompt_mod

        assert "MAX(record_date)" in prompt_mod.SQL_SYSTEM_PROMPT
        assert "CURDATE()" in prompt_mod.SQL_SYSTEM_PROMPT
        assert "呆滞" in prompt_mod.SQL_SYSTEM_PROMPT
        assert "禁止臆造" in prompt_mod.SQL_SYSTEM_PROMPT
        assert "avg_outbound" in prompt_mod.SQL_SYSTEM_PROMPT
        assert "哪些物料库存呆滞" in prompt_mod.PLAN_SYSTEM_PROMPT
        assert "相对排名" in prompt_mod.PLAN_SYSTEM_PROMPT

    def test_missing_llm_key_yields_error_frame(self, retriever, cfg):
        llm = FakeLLM([], chat_error=LLMNotConfiguredError("未配置任何 LLM API Key：请在 .env 中填写 LLM_PRIMARY_API_KEY"))
        events = _parse(_collect_frames(_make_req(), llm, retriever, cfg))
        assert events[0].type == "task_started"
        error = events[-1]
        assert error.type == "error"
        assert error.data["code"] == "LLM_NOT_CONFIGURED"
        assert error.data["message"] and error.data["suggestion"]
        assert not any(e.type == "done" for e in events)

    def test_history_is_passed_to_planner(self, retriever, cfg, patch_executor):
        patch_executor([_exec_result()])
        llm = FakeLLM([_resp(PLAN_JSON), _resp(SQL_1), _resp(CONCLUSION)])
        req = AnalyzeRequest(
            sessionId="s-1", messageId="m-2", question="那焊接呢？",
            history=[{"role": "user", "content": "请分析各工序的良率。"}, {"role": "assistant", "content": "各工序良率见上表。"}],
        )
        events = _parse(_collect_frames(req, llm, retriever, cfg))
        assert any(e.type == "done" for e in events)
        planner_messages = llm.calls[0]["messages"]
        assert any("请分析各工序的良率" in m["content"] for m in planner_messages), "历史应进入规划上下文"


# ---- API 路由（/health + /api/agent/analyze SSE）----


class TestRoutes:
    def test_health_reports_corpus_loaded(self):
        from app.main import app

        with TestClient(app) as client:
            resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["corpus_loaded"] is True

    def test_analyze_streams_sse_frames(self, monkeypatch):
        from app.api import routes
        from app.main import app

        async def fake_run(req, llm, retriever, cfg):
            yield SSEEvent(type="task_started", data={"question": req.question}).to_sse_frame()
            yield SSEEvent(type="done", data={"sql": "SELECT 1"}).to_sse_frame()

        monkeypatch.setattr(routes, "run_analysis", fake_run)
        with TestClient(app) as client:
            resp = client.post(
                "/api/agent/analyze",
                json={"sessionId": "s-1", "messageId": "m-1", "question": "请分析各工序的良率。", "history": []},
            )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert "event: task_started\ndata: " in resp.text
        assert "event: done" in resp.text

    def test_analyze_without_llm_key_returns_error_frame(self, monkeypatch):
        from app.api import routes
        from app.main import app

        keyless = Settings(
            llm_primary_api_key="", llm_fallback_api_key="",
            llm_primary_base_url="http://localhost:9", llm_fallback_base_url="http://localhost:9",
        )
        monkeypatch.setattr(routes, "get_llm", lambda: LLMClient(keyless))
        with TestClient(app) as client:
            resp = client.post(
                "/api/agent/analyze",
                json={"sessionId": "s-1", "messageId": "m-1", "question": "请分析各工序的良率。"},
            )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert "event: task_started" in resp.text
        assert "event: error" in resp.text
        payload = json.loads(resp.text.split("event: error\ndata: ", 1)[1].split("\n\n", 1)[0])
        assert payload["code"] == "LLM_NOT_CONFIGURED"
        assert payload["suggestion"]

    def test_internal_reindex_returns_counts(self, monkeypatch):
        from app.api import routes
        from app.main import app

        with TestClient(app) as client:
            resp = client.post("/internal/reindex")
        assert resp.status_code == 200
        # BUG-014：与 corpus.json 实际计数对齐（动态），运行时 reindex 同源
        assert resp.json() == _corpus_expected_counts()


class TestSqlHasGroupBy:
    """ml 模式 GROUP BY 硬约束的 AST 判定（主控修复 2026-09-20）。"""

    def test_plain_select_has_no_group(self):
        from app.orchestrator.pipeline import _sql_has_group_by

        assert _sql_has_group_by("SELECT * FROM equipment_downtime") is False

    def test_group_by_detected(self):
        from app.orchestrator.pipeline import _sql_has_group_by

        assert (
            _sql_has_group_by(
                "SELECT equipment_id, COUNT(*) AS c FROM equipment_downtime GROUP BY equipment_id"
            )
            is True
        )

    def test_cte_with_group_detected(self):
        from app.orchestrator.pipeline import _sql_has_group_by

        assert (
            _sql_has_group_by(
                "WITH t AS (SELECT equipment_id, SUM(downtime_minutes) AS m "
                "FROM equipment_downtime GROUP BY equipment_id) SELECT * FROM t"
            )
            is True
        )

    def test_parse_error_returns_false(self):
        from app.orchestrator.pipeline import _sql_has_group_by

        assert _sql_has_group_by("这不是 SQL") is False


class TestPipelineMlGroupByCorrection:
    """ml 模式下首查带 GROUP BY 时应触发一次纠正重生成（行级明细）。"""

    def test_groupby_sql_gets_corrected(self, retriever, cfg, patch_executor, monkeypatch):
        import json as _json

        from app.ml.contracts import MLResponse

        plan_ml = (
            '{"intent":"anomaly","topic":"equipment","tables":["equipment_downtime"],"metrics":[],'
            '"dimensions":[],"filters":[],"time_range":{},"execution_mode":"ml","ml_task":null,'
            '"chart_type":"scatter","expected_output":"异常设备检测"}'
        )
        sql_grouped = (
            "SELECT equipment_id, COUNT(*) AS downtime_count, SUM(downtime_minutes) AS total_minutes "
            "FROM equipment_downtime GROUP BY equipment_id"
        )
        sql_rowlevel = (
            "SELECT equipment_id, equipment_name, downtime_minutes, alarm_count "
            "FROM equipment_downtime ORDER BY start_time DESC"
        )
        ml_plan = (
            '{"model_type":"isolation_forest","features":["downtime_minutes","alarm_count"],'
            '"target":null,"parameters":{"contamination":0.1}}'
        )
        rows = [{"equipment_id": f"EQ-{i:02d}", "equipment_name": f"设备{i}", "downtime_minutes": 60 + i, "alarm_count": i} for i in range(40)]
        patch_executor([_exec_result(rowcount=40)])
        # 打桩：让 executor 返回 40 行设备明细（特征列齐全）
        import app.orchestrator.pipeline as pl

        def _fake_rows(sql, c):
            from app.sqlguard.executor import ExecResult

            return ExecResult(
                columns=list(rows[0].keys()), rows=rows, rowcount=40,
                elapsed_ms=5.0, truncated=False,
            )

        monkeypatch.setattr(pl, "execute_readonly", _fake_rows)
        canned = MLResponse(
            task_id="t1", model_type="isolation_forest", task_type="anomaly",
            metrics={"n_anomalies": 3, "threshold": 0.5},
            feature_importance=[], plots=[], predictions_sample=[], explanation="ok",
        )
        monkeypatch.setattr(pl, "run_ml", lambda req, cfg=None, prepared=None: canned)

        llm = FakeLLM([_resp(plan_ml), _resp(sql_grouped), _resp(sql_rowlevel), _resp(ml_plan), _resp("结论：检测到异常设备。")])
        frames = _collect_frames(_make_req("检测最近一个月设备数据中的异常"), llm, retriever, cfg)
        events = _parse(frames)

        sqls = [e.data["sql"] for e in events if e.type == "sql_generated"]
        assert len(sqls) == 2, f"应纠正重生成一次 SQL，实际 {len(sqls)} 次"
        assert "GROUP BY" in sqls[0].upper() and "GROUP BY" not in sqls[1].upper()
        assert any(e.type == "ml_result" for e in events), "纠正后应成功产出 ml_result"
        assert events[-1].type == "done"
