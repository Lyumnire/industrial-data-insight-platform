# AI-assisted
"""T-003 LLM 客户端单元测试（TDD 先行）。

全部 mock openai.OpenAI（patch app.llm.client.OpenAI），绝不发起真实网络调用；
time.sleep 一并 monkeypatch，测试不等待真实退避。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import APIError, APITimeoutError

from app.config import Settings
from app.llm.client import LLMClient, LLMNotConfiguredError

_ENV_KEYS = (
    "LLM_PRIMARY_BASE_URL", "LLM_PRIMARY_API_KEY", "LLM_PRIMARY_MODEL",
    "LLM_LIGHT_MODEL", "LLM_FALLBACK_BASE_URL", "LLM_FALLBACK_API_KEY",
    "LLM_FALLBACK_MODEL",
)


@pytest.fixture(autouse=True)
def _isolate_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """屏蔽本机环境变量，保证测试不读真实配置。"""
    for name in _ENV_KEYS:
        monkeypatch.delenv(name, raising=False)


def _make_cfg() -> Settings:
    return Settings(
        _env_file=None,
        llm_primary_base_url="https://mimo.test/v1",
        llm_primary_api_key="sk-primary",
        llm_primary_model="mimo-v2.5",
        llm_light_model="mimo-v2-flash",
        llm_fallback_base_url="https://fallback.test/v1",
        llm_fallback_api_key="sk-fallback",
        llm_fallback_model="deepseek-chat",
    )


def _fake_response(content: str = "ok", usage: tuple[int, int] = (0, 0)) -> SimpleNamespace:
    """模拟 openai ChatCompletion 返回对象（只含 client.py 消费的属性）。"""
    message = SimpleNamespace(content=content, tool_calls=None)
    u = SimpleNamespace(
        prompt_tokens=usage[0], completion_tokens=usage[1], total_tokens=usage[0] + usage[1]
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=u)


class _RetryableAPIError(APIError):
    """模拟主力限流/5xx/连接类可重试错误（避免依赖各版本 APIConnectionError 签名差异）。"""

    def __init__(self) -> None:
        super().__init__(
            "simulated primary failure",
            request=httpx.Request("POST", "https://mimo.test/v1/chat/completions"),
            body=None,
        )


def _install_fake_openai(
    monkeypatch: pytest.MonkeyPatch, primary: Any, fallback: Any
) -> dict[str, list[dict]]:
    """把 app.llm.client.OpenAI 换成假客户端，返回按 provider 记录的 create 调用列表。

    behavior 可为：异常实例（每次 raise）、普通返回值（每次 return）、
    list（按调用次序消费，最后一项重复）或 callable(kwargs)。
    """
    calls: dict[str, list[dict]] = {"primary": [], "fallback": []}

    class _FakeOpenAI:
        def __init__(self, base_url: str = "", api_key: str = "", timeout: float | None = None):
            self.tag = "primary" if api_key == "sk-primary" else "fallback"
            self._behavior = primary if self.tag == "primary" else fallback

        def _create(self, **kwargs: Any) -> Any:
            attempt_idx = len(calls[self.tag])
            calls[self.tag].append(kwargs)
            b = self._behavior
            if isinstance(b, list):
                b = b[min(attempt_idx, len(b) - 1)]
            if isinstance(b, Exception):
                raise b
            if callable(b):
                return b(kwargs)
            return b

        @property
        def chat(self) -> SimpleNamespace:  # 对齐 openai SDK 的 client.chat.completions.create 结构
            return SimpleNamespace(completions=SimpleNamespace(create=self._create))

    monkeypatch.setattr("app.llm.client.OpenAI", _FakeOpenAI)
    return calls


def test_failover_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """主力持续超时：按重试语义尝试 2 次后自动切兜底成功。"""
    req = httpx.Request("POST", "https://mimo.test/v1/chat/completions")
    calls = _install_fake_openai(monkeypatch, primary=APITimeoutError(req),
                                 fallback=_fake_response("fallback-ok"))
    sleeps: list[float] = []
    monkeypatch.setattr("app.llm.client.time.sleep", sleeps.append)
    client = LLMClient(_make_cfg())

    resp = client.chat([{"role": "user", "content": "请分析各工序的良率"}])

    assert resp.provider == "fallback"
    assert resp.content == "fallback-ok"
    assert len(calls["primary"]) == 2   # 1 次原始 + 1 次重试
    assert len(calls["fallback"]) == 1
    assert sleeps == [1.0]              # 主力重试前退避一次；切换 provider 不等待


def test_retry_then_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """主力重试 1 次仍失败 -> 兜底；兜底也先失败 1 次再成功，验证指数退避 1s -> 2s。"""
    calls = _install_fake_openai(monkeypatch, primary=_RetryableAPIError(),
                                 fallback=[_RetryableAPIError(), _fake_response("ok-after-fallback")])
    sleeps: list[float] = []
    monkeypatch.setattr("app.llm.client.time.sleep", sleeps.append)
    client = LLMClient(_make_cfg())

    resp = client.chat([{"role": "user", "content": "hi"}])

    assert resp.provider == "fallback"
    assert resp.content == "ok-after-fallback"
    assert len(calls["primary"]) == 2
    assert len(calls["fallback"]) == 2
    assert sleeps == [1.0, 2.0]         # 指数退避：1s -> 2s


def test_light_tier_routes_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """model_tier="light" 路由到 cfg.llm_light_model；默认 heavy 用主力完整模型。"""
    calls = _install_fake_openai(monkeypatch, primary=_fake_response("tier-ok"),
                                 fallback=_fake_response("should-not-be-used"))
    monkeypatch.setattr("app.llm.client.time.sleep", lambda _s: None)
    client = LLMClient(_make_cfg())

    light = client.chat([{"role": "user", "content": "意图分类"}], model_tier="light")
    heavy = client.chat([{"role": "user", "content": "生成 SQL"}])

    assert light.provider == "primary" and light.content == "tier-ok"
    assert heavy.provider == "primary"
    assert calls["primary"][0]["model"] == "mimo-v2-flash"  # = cfg.llm_light_model
    assert calls["primary"][1]["model"] == "mimo-v2.5"      # 默认 heavy
    assert calls["fallback"] == []


def test_usage_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    """返回 usage 并累加到 client.total_usage（成本日志基础，docs/02 §4）。"""
    _install_fake_openai(monkeypatch, primary=_fake_response("ok", usage=(12, 8)), fallback=None)
    monkeypatch.setattr("app.llm.client.time.sleep", lambda _s: None)
    client = LLMClient(_make_cfg())

    resp = client.chat([{"role": "user", "content": "hi"}])
    assert resp.usage == {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}
    assert client.total_usage == {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}

    client.chat([{"role": "user", "content": "hi again"}])
    assert client.total_usage == {"prompt_tokens": 24, "completion_tokens": 16, "total_tokens": 40}


def test_no_key_raises_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """主力与兜底都未配 Key 时抛带清晰指引的 LLMNotConfiguredError。"""
    _install_fake_openai(monkeypatch, primary=None, fallback=None)  # 不应被实例化
    client = LLMClient(Settings(_env_file=None, llm_primary_api_key="", llm_fallback_api_key=""))

    with pytest.raises(LLMNotConfiguredError) as excinfo:
        client.chat([{"role": "user", "content": "hi"}])
    msg = str(excinfo.value)
    assert "LLM_PRIMARY_API_KEY" in msg and "LLM_FALLBACK_API_KEY" in msg
    assert ".env.example" in msg


def test_tools_and_response_format_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    """tools / response_format 原样透传给 SDK create()。"""
    calls = _install_fake_openai(monkeypatch, primary=_fake_response("json"), fallback=None)
    monkeypatch.setattr("app.llm.client.time.sleep", lambda _s: None)
    client = LLMClient(_make_cfg())

    tools = [{"type": "function", "function": {"name": "execute_sql", "parameters": {}}}]
    resp = client.chat([{"role": "user", "content": "q"}], tools=tools,
                       response_format={"type": "json_object"})

    assert resp.content == "json"
    assert calls["primary"][0]["tools"] == tools
    assert calls["primary"][0]["response_format"] == {"type": "json_object"}


def test_tool_calls_extracted(monkeypatch: pytest.MonkeyPatch) -> None:
    """tool_calls 归一化为 plain dict，供编排器状态机消费。"""
    payload = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[
            SimpleNamespace(id="call_1", type="function",
                            function=SimpleNamespace(name="execute_sql", arguments='{"sql": "SELECT 1"}'))
        ]))],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )
    _install_fake_openai(monkeypatch, primary=payload, fallback=None)
    monkeypatch.setattr("app.llm.client.time.sleep", lambda _s: None)
    client = LLMClient(_make_cfg())

    resp = client.chat([{"role": "user", "content": "q"}])
    assert resp.tool_calls == [{
        "id": "call_1", "type": "function",
        "function": {"name": "execute_sql", "arguments": '{"sql": "SELECT 1"}'},
    }]
