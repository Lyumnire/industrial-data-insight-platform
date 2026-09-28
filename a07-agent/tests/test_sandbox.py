# AI-assisted
"""T-011 沙箱 Python 执行器测试（P2a 计划 §Task 11.1，先于实现编写——严格 TDD）。

覆盖面：
- 合法 pandas 代码执行并返回 JSON 结果（stats / tables）
- import 白名单钩子：os/socket/subprocess 等一律 ImportError 拒绝
- 死循环超时（2s）强制终止并返回可读错误
- stdout 超限截断、大输出 print 不致崩
- 工作目录隔离（临时目录外无落盘）+ 用后清理
- Windows Job Object 限额器（内存上限 / KILL_ON_JOB_CLOSE / 进程归属）
- 分析任务模板 correlation / group_summary
- pipeline execution_mode="python" 分支（mock LLM + 真沙箱）
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app.analytics.tasks import render_template, template_catalog, template_names
from app.config import Settings
from app.retriever import DEFAULT_CORPUS_PATH, Retriever
from app.sandbox.runner import SandboxResult, run_python
from app.sqlguard.executor import ExecResult

# ---- 沙箱执行器 ----


@pytest.fixture
def csv_path(tmp_path: Path) -> str:
    p = tmp_path / "in.csv"
    p.write_text(
        "qty,rate,cat\n1,0.1,A\n2,0.2,A\n3,0.3,B\n4,0.4,B\n",
        encoding="utf-8",
    )
    return str(p)


def _sandbox_temp_dirs() -> set[str]:
    return {str(p) for p in Path(tempfile.gettempdir()).glob("a07_sandbox_*")}


class TestRunPythonHappyPath:
    def test_pandas_stats_result(self, csv_path):
        code = "result['total'] = float(df['qty'].sum())\nresult['rows'] = int(len(df))\n"
        res = run_python(code, csv_path, timeout_s=20)
        assert res.ok, res.error
        assert res.error is None
        assert res.stats["total"] == pytest.approx(10.0)
        assert res.stats["rows"] == 4

    def test_dataframe_to_table(self, csv_path):
        code = "result['tables'] = [df]\n"
        res = run_python(code, csv_path, timeout_s=20)
        assert res.ok, res.error
        assert res.tables, "result['tables'] 应转换为 tables"
        table = res.tables[0]
        assert table["columns"] == ["qty", "rate", "cat"]
        assert len(table["rows"]) == 4
        assert table["rows"][0]["qty"] == 1

    def test_stdout_captured_in_tail(self, csv_path):
        code = "print('hello sandbox')\nresult['v'] = 1\n"
        res = run_python(code, csv_path, timeout_s=20)
        assert res.ok, res.error
        assert "hello sandbox" in res.stdout_tail
        assert res.stats["v"] == 1

    def test_without_input_csv(self):
        res = run_python("result['v'] = 42\n", None, timeout_s=20)
        assert res.ok, res.error
        assert res.stats["v"] == 42

    def test_sandbox_error_key_is_soft_failure(self, csv_path):
        # 模板/代码自身写 result['error'] 属业务层失败：执行本身成功（ok=True），交编排层裁决
        res = run_python("result['error'] = '样本不足'\n", csv_path, timeout_s=20)
        assert res.ok, res.error
        assert res.stats["error"] == "样本不足"


class TestImportWhitelist:
    @pytest.mark.parametrize("module", ["os", "socket", "subprocess"])
    def test_dangerous_import_rejected(self, csv_path, module):
        res = run_python(f"import {module}\nresult['v'] = 1\n", csv_path, timeout_s=20)
        assert res.ok is False
        assert res.stats == {}
        assert module in res.error, f"错误信息应指出被拒模块：{res.error!r}"
        assert "白名单" in res.error

    def test_dunder_import_also_blocked(self, csv_path):
        res = run_python("result['v'] = __import__('socket').socket\n", csv_path, timeout_s=20)
        assert res.ok is False
        assert "socket" in res.error

    def test_whitelist_modules_importable(self, csv_path):
        code = (
            "import pandas, numpy, json, math, statistics, datetime, re\n"
            "from datetime import timedelta\n"
            "result['v'] = math.floor(1.9) + int(timedelta(days=1).total_seconds())\n"
        )
        res = run_python(code, csv_path, timeout_s=20)
        assert res.ok, res.error
        assert res.stats["v"] == 86401


class TestTimeoutAndOutput:
    def test_infinite_loop_killed_by_timeout(self, csv_path):
        started = time.perf_counter()
        res = run_python("while True:\n    x = 1\n", csv_path, timeout_s=2)
        elapsed = time.perf_counter() - started
        assert res.ok is False
        assert "超时" in res.error
        assert "2" in res.error, f"错误应包含超时秒数：{res.error!r}"
        assert elapsed < 30, f"超时后应立即终止而非挂死（实际 {elapsed:.1f}s）"

    def test_stdout_overflow_truncated(self, csv_path):
        # ~10MB print：不得崩、结果仍可解析、尾巴限幅并标注截断
        code = "for _i in range(2000):\n    print('A' * 5000)\nresult['v'] = 1\n"
        res = run_python(code, csv_path, timeout_s=30)
        assert res.ok, res.error
        assert res.stats["v"] == 1
        assert len(res.stdout_tail) < 20000, f"stdout 尾巴应限幅（实际 {len(res.stdout_tail)} 字符）"
        assert "截断" in res.stdout_tail


class TestWorkdirIsolation:
    def test_file_write_confined_to_temp_workdir_and_cleaned(self, csv_path):
        before = _sandbox_temp_dirs()
        res = run_python("open('escape_probe.txt', 'w').write('x')\nresult['v'] = 1\n", csv_path, timeout_s=20)
        assert res.ok, res.error
        assert res.stats["v"] == 1
        # 相对路径写文件落在沙箱临时工作目录，而不是引擎/测试进程的工作目录
        assert not (Path.cwd() / "escape_probe.txt").exists()
        assert not (Path(__file__).parent / "escape_probe.txt").exists()
        # 用后清理：不留 a07_sandbox_* 目录
        time.sleep(0.2)
        assert _sandbox_temp_dirs() == before, f"沙箱临时目录未清理：{_sandbox_temp_dirs() - before}"


class TestReadableErrors:
    def test_syntax_error_readable(self, csv_path):
        res = run_python("def f(:\n    pass\n", csv_path, timeout_s=20)
        assert res.ok is False
        assert res.error and "SyntaxError" in res.error

    def test_runtime_error_readable(self, csv_path):
        res = run_python("x = 1 / 0\n", csv_path, timeout_s=20)
        assert res.ok is False
        assert res.error and "ZeroDivisionError" in res.error

    def test_missing_input_csv(self, tmp_path):
        res = run_python("result['v'] = 1\n", str(tmp_path / "no_such.csv"), timeout_s=20)
        assert res.ok is False
        assert res.error and "不存在" in res.error


# ---- Windows Job Object 限额器（§Task 11.2）----


class TestJobObjectLimiter:
    def test_memory_and_kill_on_close_flags(self):
        from app.sandbox import limits_win

        if not limits_win.HAS_JOB_OBJECT:
            pytest.skip("pywin32 不可用（本机应为可用）")
        limiter = limits_win.WindowsJobLimiter(memory_mb=256)
        try:
            info = limits_win.win32job.QueryInformationJobObject(
                limiter.handle, limits_win.win32job.JobObjectExtendedLimitInformation
            )
            flags = info["BasicLimitInformation"]["LimitFlags"]
            assert flags & limits_win.win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
            assert flags & limits_win.win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            assert info["ProcessMemoryLimit"] == 256 * 1024 * 1024
        finally:
            limiter.close()

    def test_child_process_joins_job(self):
        from app.sandbox import limits_win

        if not limits_win.HAS_JOB_OBJECT:
            pytest.skip("pywin32 不可用（本机应为可用）")
        limiter = limits_win.create_job_limiter()
        assert limiter is not None, "Windows 上应能创建 Job Object"
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
        try:
            limiter.assign(proc)
            time.sleep(0.5)
            accounting = limits_win.win32job.QueryInformationJobObject(
                limiter.handle, limits_win.win32job.JobObjectBasicAccountingInformation
            )
            assert accounting["TotalProcesses"] >= 1, "子进程应已加入 Job Object"
        finally:
            proc.kill()
            proc.wait(timeout=5)
            limiter.close()

    def test_run_python_attaches_job_without_error(self, csv_path):
        from app.sandbox import limits_win

        res = run_python("result['v'] = 7\n", csv_path, timeout_s=20)
        assert res.ok, res.error
        if limits_win.HAS_JOB_OBJECT:
            assert not any("Job Object" in w for w in res.warnings), (
                f"Job Object 可用时不应出现降级警告：{res.warnings}"
            )


# ---- 分析任务模板（§Task 11.4）----


class TestAnalyticsTemplates:
    def test_template_names_and_catalog(self):
        assert set(template_names()) >= {"correlation", "group_summary"}
        catalog = template_catalog()
        assert "correlation" in catalog and "group_summary" in catalog

    def test_correlation_template_runs(self, csv_path):
        code = render_template("correlation", {"x_col": "qty", "y_col": "rate"})
        assert "corr" in code
        res = run_python(code, csv_path, timeout_s=20)
        assert res.ok, res.error
        # qty 与 rate 完全线性相关 → Pearson ≈ 1
        assert res.stats["pearson"] == pytest.approx(1.0, abs=1e-6)
        assert res.stats["spearman"] == pytest.approx(1.0, abs=1e-6)
        assert res.stats["n"] == 4
        assert "Pearson" in res.stats["summary"]
        scatter = res.result.get("scatter")
        assert isinstance(scatter, dict)
        assert scatter["x"] == "qty" and scatter["y"] == "rate"
        assert len(scatter["points"]) == 4
        assert scatter["points"][0] == [1.0, 0.1]

    def test_correlation_template_missing_params_rejected(self):
        with pytest.raises(ValueError):
            render_template("correlation", {"x_col": "qty"})

    def test_group_summary_template_runs(self, csv_path):
        code = render_template("group_summary", {"group_col": "cat", "value_col": "qty", "agg": "sum"})
        res = run_python(code, csv_path, timeout_s=20)
        assert res.ok, res.error
        assert res.tables, "group_summary 应产出聚合表"
        table = res.tables[0]
        assert table["columns"][0] == "cat"
        rows = {r["cat"]: r for r in table["rows"]}
        assert rows["A"]["sum_qty"] == 3
        assert rows["B"]["sum_qty"] == 7
        assert "summary" in res.stats

    def test_group_summary_invalid_agg_rejected(self):
        with pytest.raises(ValueError):
            render_template("group_summary", {"group_col": "cat", "value_col": "qty", "agg": "DROP TABLE"})

    def test_unknown_template_rejected(self):
        with pytest.raises(ValueError):
            render_template("rm_rf_slash", {})


# ---- pipeline execution_mode="python" 分支（§Task 11.5，mock LLM + 真沙箱）----


PLAN_PY_JSON = (
    '{"intent":"correlation","topic":"equipment","tables":["equipment_downtime"],'
    '"metrics":[],"dimensions":[],"filters":[],"time_range":{},"execution_mode":"python",'
    '"chart_type":"scatter","expected_output":"设备停机时间和不良率的相关性"}'
)

PY_GEN_JSON = json.dumps(
    {"template": "correlation", "params": {"x_col": "downtime_minutes", "y_col": "defect_rate"}},
    ensure_ascii=False,
)

PY_CONCLUSION = (
    "停机时长与不良率的 Pearson 相关系数为 0.98，呈强正相关，停机越久不良率越高。"
    "口径说明：相关性由 pandas 在沙箱内按日明细计算。"
)


def _py_exec_result() -> ExecResult:
    rows = [
        {"downtime_minutes": float(m), "defect_rate": round(m * 0.01 + 0.1, 4)}
        for m in (10, 20, 30, 40, 50, 60)
    ]
    return ExecResult(
        columns=["downtime_minutes", "defect_rate"],
        rows=rows,
        rowcount=6,
        elapsed_ms=5.0,
        truncated=False,
    )


class _FakeLLM:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, *, model_tier="heavy", tools=None, response_format=None):
        self.calls.append({"messages": messages, "model_tier": model_tier})
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


class TestPipelinePythonMode:
    def _req(self) -> Any:
        from app.api.routes import AnalyzeRequest

        return AnalyzeRequest(
            sessionId="s-py", messageId="m-py",
            question="分析设备停机时间和不良率是否相关", history=[],
        )

    def test_correlation_flow_events(self, retriever, cfg, patch_executor):
        from app.api.routes import AnalyzeRequest  # noqa: F401  确认可导入

        patch_executor([_py_exec_result()])
        llm = _FakeLLM([
            _resp(PLAN_PY_JSON),
            _resp("SELECT production_date, SUM(downtime_minutes) AS downtime_minutes, "
                  "AVG(defect_rate) AS defect_rate FROM equipment_downtime GROUP BY production_date"),
            _resp(PY_GEN_JSON),
            _resp(PY_CONCLUSION),
        ])
        events = _parse_frames(_collect(self._req(), llm, retriever, cfg))
        types = [e.type for e in events]

        assert "error" not in types, next((e.data for e in events if e.type == "error"), None)
        assert types[-1] == "done"
        # ① code_generated：language=python，代码为 correlation 模板
        code_ev = next(e for e in events if e.type == "code_generated")
        assert code_ev.data["language"] == "python"
        assert "corr" in code_ev.data["code"]
        # ② chart：scatter 且带散点数据
        chart = next(e for e in events if e.type == "chart")
        assert chart.data["type"] == "scatter"
        assert chart.data["option"]["series"][0]["type"] == "scatter"
        assert len(chart.data["option"]["series"][0]["data"]) == 6
        # ③ done：标准对象含 python_code + insights 含相关系数文本
        done = next(e for e in events if e.type == "done")
        assert "corr" in (done.data.get("python_code") or "")
        assert any("Pearson" in s for s in done.data["insights"]), done.data["insights"]
        assert any("0.9" in s or "1.0" in s for s in done.data["insights"])
        # 结论流式事件仍然存在（协议沿用）
        assert "text_delta" in types

    def test_correlation_intent_forces_python_mode(self, retriever, cfg, patch_executor):
        # 编排矫正：规划器把相关性问题填成 execution_mode=sql 时，pipeline 强制纠正为
        # python（P2a §Task 11 场景 3，真实冒烟实测 light 档规划不稳）
        plan_json = PLAN_PY_JSON.replace('"execution_mode":"python"', '"execution_mode":"sql"')
        patch_executor([_py_exec_result()])
        llm = _FakeLLM([
            _resp(plan_json),
            _resp("SELECT production_date, SUM(downtime_minutes) AS downtime_minutes, "
                  "AVG(defect_rate) AS defect_rate FROM equipment_downtime GROUP BY production_date"),
            _resp(PY_GEN_JSON),
            _resp(PY_CONCLUSION),
        ])
        events = _parse_frames(_collect(self._req(), llm, retriever, cfg))
        types = [e.type for e in events]

        plan_ready = next(e for e in events if e.type == "plan_ready")
        assert plan_ready.data["execution_mode"] == "python", "correlation 意图应被纠正为 python"
        assert "code_generated" in types
        assert "error" not in types
        done = next(e for e in events if e.type == "done")
        assert done.data.get("python_code")

    def test_codegen_failure_degrades_to_table_analysis(self, retriever, cfg, patch_executor):
        patch_executor([_py_exec_result()])
        llm = _FakeLLM([
            _resp(PLAN_PY_JSON),
            _resp("SELECT 1"),
            _resp("这不是JSON"),   # 代码生成第 1 次失败
            _resp("{{{{"),          # 重试仍失败 → 降级
            _resp("降级后的普通结论。"),
        ])
        events = _parse_frames(_collect(self._req(), llm, retriever, cfg))
        types = [e.type for e in events]

        assert "error" not in types
        assert "code_generated" not in types, "代码生成失败不得发出 code_generated"
        assert types[-1] == "done"
        done = next(e for e in events if e.type == "done")
        assert any("Python" in w for w in done.data["warnings"]), done.data["warnings"]
        assert "chart" in types, "降级后应走普通图表路径"
        assert done.data.get("python_code") in (None, "")

    def test_sandbox_runtime_failure_degrades(self, retriever, cfg, patch_executor):
        patch_executor([_py_exec_result()])
        bad_code = json.dumps({"template": None, "code": "import os\nresult['v'] = 1\n"}, ensure_ascii=False)
        llm = _FakeLLM([
            _resp(PLAN_PY_JSON),
            _resp("SELECT 1"),
            _resp(bad_code),        # 生成成功但 import os 被沙箱拒绝
            _resp("降级后的普通结论。"),
        ])
        events = _parse_frames(_collect(self._req(), llm, retriever, cfg))
        types = [e.type for e in events]

        assert "error" not in types
        code_ev = next(e for e in events if e.type == "code_generated")
        assert "import os" in code_ev.data["code"]
        assert types[-1] == "done"
        done = next(e for e in events if e.type == "done")
        assert any("Python" in w for w in done.data["warnings"]), done.data["warnings"]
        assert any("白名单" in w or "os" in w for w in done.data["warnings"]), done.data["warnings"]


# ---- BUG-017 / T-028：group_summary 模板 LLM 路径（列名 vs 枚举参数分离）----

PLAN_GS_JSON = (
    '{"intent":"query","topic":"quality","tables":["process_output"],"metrics":["工序良率"],'
    '"dimensions":["process_name"],"filters":[],"time_range":{},"execution_mode":"python",'
    '"chart_type":"bar","expected_output":"各工序良率分组汇总"}'
)

GS_GEN_JSON = json.dumps(
    {
        "template": "group_summary",
        "params": {"group_col": "process_name", "value_col": "yield_rate", "agg": "mean"},
    },
    ensure_ascii=False,
)

GS_CONCLUSION = (
    "按工序分组对良率做 mean 汇总：注塑最高，焊接最低。"
    "口径说明：分组汇总由沙箱 group_summary 模板执行。"
)


def _gs_exec_result() -> ExecResult:
    rows = [
        {"process_name": "注塑", "yield_rate": 97.0},
        {"process_name": "注塑", "yield_rate": 98.0},
        {"process_name": "焊接", "yield_rate": 90.0},
        {"process_name": "焊接", "yield_rate": 92.0},
        {"process_name": "装配", "yield_rate": 96.0},
        {"process_name": "装配", "yield_rate": 97.0},
    ]
    return ExecResult(
        columns=["process_name", "yield_rate"],
        rows=rows,
        rowcount=6,
        elapsed_ms=4.0,
        truncated=False,
    )


class TestPipelineGroupSummaryTemplatePath:
    """BUG-017 修复后：group_summary 的 LLM 模板选择路径应可用（agg 枚举不再被误伤）。"""

    def _req(self) -> Any:
        from app.api.routes import AnalyzeRequest

        return AnalyzeRequest(
            sessionId="s-gs", messageId="m-gs",
            question="各工序良率分组汇总对比", history=[],
        )

    def test_group_summary_llm_path_reaches_sandbox(self, retriever, cfg, patch_executor):
        patch_executor([_gs_exec_result()])
        llm = _FakeLLM([
            _resp(PLAN_GS_JSON),
            _resp("SELECT process_name, yield_rate FROM process_output ORDER BY process_name"),
            _resp(GS_GEN_JSON),
            _resp(GS_CONCLUSION),
        ])
        events = _parse_frames(_collect(self._req(), llm, retriever, cfg))
        types = [e.type for e in events]

        assert "error" not in types, next((e.data for e in events if e.type == "error"), None)
        code_ev = next(e for e in events if e.type == "code_generated")
        assert code_ev.data["language"] == "python"
        assert "group_summary" in code_ev.data["source"] or "group" in code_ev.data["code"]
        assert "_agg" in code_ev.data["code"], "应渲染 group_summary 模板代码"
        # 沙箱执行成功 → done 携带 python_code 与 insights
        done = next(e for e in events if e.type == "done")
        assert types[-1] == "done"
        assert done.data.get("python_code")
        assert "group" in (done.data.get("python_code") or "") or "_agg" in (done.data.get("python_code") or "")
        # 不得因 BUG-017 参数误伤而降级
        assert not any("代码生成失败" in w or "降级" in w for w in done.data.get("warnings") or []), \
            done.data.get("warnings")
