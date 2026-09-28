# AI-assisted: P1 端到端冒烟测试（docs/plans/2026-09-19-P1-走通骨架.md §Task 8）
# 验证"请分析各工序的良率"全链路：收题→检索→SQL 生成→校验→执行→图表→结论。
# 需要：引擎已启动(8100)、.env 已配置 LLM Key、mes_demo 已导入数据。
# 无 Key/引擎未启动时自动跳过（门禁中显示 SKIP 而非 FAIL）。
import json
import os

import pytest

RUN_E2E = os.environ.get("E2E_SMOKE") == "1"
BASE = os.environ.get("AGENT_BASE_URL", "http://localhost:8100")

pytestmark = pytest.mark.skipif(
    not RUN_E2E, reason="设置 E2E_SMOKE=1 且引擎已启动、LLM Key 已配置后运行真实冒烟"
)


def _sse_frames(resp):
    """把 SSE 响应文本解析为 (event, data_dict) 序列。"""
    for block in resp.text.split("\n\n"):
        lines = block.strip().splitlines()
        if not lines:
            continue
        ev, data = None, None
        for ln in lines:
            if ln.startswith("event:"):
                ev = ln.split(":", 1)[1].strip()
            elif ln.startswith("data:"):
                data = json.loads(ln.split(":", 1)[1])
        if ev:
            yield ev, data


def test_demo1_yield_by_process():
    import httpx

    resp = httpx.post(
        f"{BASE}/api/agent/analyze",
        json={"sessionId": "smoke-s1", "messageId": "smoke-m1", "question": "请分析各工序的良率。", "history": []},
        timeout=120,
    )
    assert resp.status_code == 200
    frames = list(_sse_frames(resp))
    types = [ev for ev, _ in frames]
    data = {ev: d for ev, d in frames}

    # 1) 规划与主题识别
    assert "plan_ready" in types
    # 2) SQL 生成且通过安全校验
    assert "sql_generated" in types and "sql_validated" in types
    # 3) 执行成功
    assert "sql_completed" in types
    # 4) 表格：5 个工序、含良率列
    assert "table" in types
    cols = [c.lower() for c in data["table"].get("columns", [])]
    assert data["table"].get("rows"), "结果行不应为空"
    assert any("process" in c or "工序" in c for c in cols), f"缺工序列: {cols}"
    assert any("yield" in c or "良率" in c for c in cols), f"缺良率列: {cols}"
    # 5) 图表配置由后端拼装
    assert "chart" in types
    opt = data["chart"]["option"]
    assert opt["series"] and opt["xAxis"], "ECharts option 不完整"
    # 6) 结论流式且含数字
    assert "text_delta" in types
    # 7) 无错误收尾
    assert "error" not in types, data.get("error")
    assert types[-1] == "done"
