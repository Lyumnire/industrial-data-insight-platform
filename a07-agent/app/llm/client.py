# AI-assisted
"""A9 LLM 客户端：OpenAI 兼容协议统一封装（docs/02 §1.2/§4、docs/03 §3.3 A9）。

策略（评审重点，改动前先读 docs/03 §6 异常处理策略）：
- failover 顺序：主力 primary（按 model_tier 选模型）→ 兜底 fallback（恒用重任务模型）；
  兜底不提供 light 档，light 请求落到兜底时用兜底模型并记 warning。
- 重试语义：每个 provider 最多尝试 2 次（原始 1 次 + 重试 1 次，"重试各 1 次"），
  重试前指数退避（BACKOFF_BASE_SECONDS * 2^(attempt-1)，即 1s -> 2s）；
  provider 之间切换不等待。全部 provider 均失败才抛 LLMError（编排器据此发 error 事件）。
- 可重试错误：openai.APIError 全系（含 APITimeoutError / APIConnectionError /
  APIStatusError 限流与 5xx），与 docs/03 §6 "LLM 超时/限流" 行一致。
- 红线 R3：Key 只来自环境变量/.env，绝不写日志；R8：单次请求 60s 超时 + 结构化日志。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Iterator

from openai import APIError, OpenAI
from pydantic import BaseModel

from app.config import LLMProviderConfig, Settings

logger = logging.getLogger("a07.llm")

ATTEMPTS_PER_PROVIDER = 2   # 每 provider：1 次原始调用 + 1 次重试
BACKOFF_BASE_SECONDS = 1.0  # 重试退避基数：1s, 2s（指数）
LLM_TIMEOUT_SECONDS = 60.0  # 单次 HTTP 请求超时（红线 R8）


class LLMNotConfiguredError(RuntimeError):
    """主力与兜底均未配置 API Key。"""


class LLMError(RuntimeError):
    """所有 provider 的重试与 failover 均失败。"""


class LLMResponse(BaseModel):
    """chat() 的归一化返回；LLM SDK 原始对象不外泄到编排层。"""

    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    usage: dict[str, int] | None = None
    provider: str = ""


class LLMClient:
    """OpenAI 兼容统一客户端：主力→兜底 failover，指数退避重试各 1 次。"""

    def __init__(self, cfg: Settings) -> None:
        self._cfg = cfg
        self._primary = self._mk(cfg.llm_primary)
        self._fallback = self._mk(cfg.llm_fallback)
        # 进程级累计用量（token 成本日志的基础，docs/02 §4 工程要求）
        self.total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    @staticmethod
    def _mk(provider: LLMProviderConfig) -> OpenAI | None:
        # 未配置 Key 的 provider 直接置 None，failover 时跳过（引擎可在无 Key 时启动）
        if not provider.api_key:
            return None
        return OpenAI(base_url=provider.base_url, api_key=provider.api_key, timeout=LLM_TIMEOUT_SECONDS)

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model_tier: str = "heavy",
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """阻塞式单轮对话；分层路由 heavy=主力完整模型 / light=主力 flash 档（docs/03 A9）。"""
        if model_tier not in ("heavy", "light"):
            raise ValueError(f"未知 model_tier: {model_tier!r}（允许 heavy/light）")
        if self._primary is None and self._fallback is None:
            raise LLMNotConfiguredError(
                "未配置任何 LLM API Key：请在 .env 中填写 LLM_PRIMARY_API_KEY（主力）"
                "或 LLM_FALLBACK_API_KEY（兜底）后重启引擎；字段样例见 .env.example"
            )

        # 尝试序列：primary(tier 模型) → fallback(heavy 模型)
        attempts: list[tuple[str, OpenAI, str]] = []
        if self._primary is not None:
            primary_model = self._cfg.llm_primary_model
            if model_tier == "light":
                primary_model = self._cfg.llm_light_model or self._cfg.llm_primary_model
            attempts.append((self._cfg.llm_primary.name, self._primary, primary_model))
        else:
            logger.warning("llm_primary_skipped reason=no_api_key")
        if self._fallback is not None:
            if model_tier == "light":
                logger.warning("llm_light_on_fallback model=%s", self._cfg.llm_fallback_model)
            attempts.append((self._cfg.llm_fallback.name, self._fallback, self._cfg.llm_fallback_model))

        last_provider, last_model, last_error = "", "", None
        retry_no = 0  # 同一次 chat() 内的总重试序号：退避跨 provider 持续指数增长，
                      # 避免主力与兜底同源故障时被密集重试
        for provider_name, client, model in attempts:
            for attempt in range(1, ATTEMPTS_PER_PROVIDER + 1):
                started = time.perf_counter()
                try:
                    kwargs: dict[str, Any] = {"model": model, "messages": messages}
                    if tools:
                        kwargs["tools"] = tools
                    if response_format:
                        kwargs["response_format"] = response_format
                    raw = client.chat.completions.create(**kwargs)
                    return self._to_response(provider_name, model, raw, started)
                except APIError as exc:  # 含 Timeout / Connection / 限流 / 5xx
                    last_provider, last_model, last_error = provider_name, model, exc
                    logger.warning(
                        "llm_attempt_failed provider=%s model=%s attempt=%d/%d elapsed_ms=%d error=%s",
                        provider_name,
                        model,
                        attempt,
                        ATTEMPTS_PER_PROVIDER,
                        int((time.perf_counter() - started) * 1000),
                        exc,
                    )
                    if attempt < ATTEMPTS_PER_PROVIDER:
                        retry_no += 1
                        time.sleep(BACKOFF_BASE_SECONDS * (2 ** (retry_no - 1)))
        raise LLMError(
            f"主力与兜底 LLM 均调用失败（最后尝试 provider={last_provider} "
            f"model={last_model}: {last_error}）"
        )

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model_tier: str = "heavy",
    ) -> Iterator[str]:
        """流式单轮对话：逐片段 yield 增量文本（仅 delta.content 非空片段）。

        复用 chat() 的 failover 与重试语义（连接建立失败按原策略重试/failover）；
        流一旦建立，中途失败**不重试**，包装为 LLMError 直接上抛，由调用方
        （编排器）走 error 帧收尾（docs/03 §6：已开始的流式输出不可回退重放）。
        usage 尽力而为：stream_options={"include_usage": True}，取最终 chunk 的
        usage 累加；部分兼容网关不回传 usage 时按 0 记录（结构化日志可追溯）。
        """
        if model_tier not in ("heavy", "light"):
            raise ValueError(f"未知 model_tier: {model_tier!r}（允许 heavy/light）")
        if self._primary is None and self._fallback is None:
            raise LLMNotConfiguredError(
                "未配置任何 LLM API Key：请在 .env 中填写 LLM_PRIMARY_API_KEY（主力）"
                "或 LLM_FALLBACK_API_KEY（兜底）后重启引擎；字段样例见 .env.example"
            )

        attempts: list[tuple[str, OpenAI, str]] = []
        if self._primary is not None:
            primary_model = self._cfg.llm_primary_model
            if model_tier == "light":
                primary_model = self._cfg.llm_light_model or self._cfg.llm_primary_model
            attempts.append((self._cfg.llm_primary.name, self._primary, primary_model))
        else:
            logger.warning("llm_primary_skipped reason=no_api_key")
        if self._fallback is not None:
            if model_tier == "light":
                logger.warning("llm_light_on_fallback model=%s", self._cfg.llm_fallback_model)
            attempts.append((self._cfg.llm_fallback.name, self._fallback, self._cfg.llm_fallback_model))

        last_provider, last_model, last_error = "", "", None
        retry_no = 0
        for provider_name, client, model in attempts:
            for attempt in range(1, ATTEMPTS_PER_PROVIDER + 1):
                started = time.perf_counter()
                try:
                    stream = client.chat.completions.create(
                        model=model,
                        messages=messages,
                        stream=True,
                        stream_options={"include_usage": True},
                    )
                except APIError as exc:  # 连接/建流阶段失败：与 chat() 同策略重试+failover
                    last_provider, last_model, last_error = provider_name, model, exc
                    logger.warning(
                        "llm_stream_attempt_failed provider=%s model=%s attempt=%d/%d elapsed_ms=%d error=%s",
                        provider_name,
                        model,
                        attempt,
                        ATTEMPTS_PER_PROVIDER,
                        int((time.perf_counter() - started) * 1000),
                        exc,
                    )
                    if attempt < ATTEMPTS_PER_PROVIDER:
                        retry_no += 1
                        time.sleep(BACKOFF_BASE_SECONDS * (2 ** (retry_no - 1)))
                    continue
                # 流已建立：中途失败不重试，直接上抛 LLMError 让调用方走 error 帧
                yield from self._iter_stream(provider_name, model, stream, started)
                return
        raise LLMError(
            f"主力与兜底 LLM 均调用失败（最后尝试 provider={last_provider} "
            f"model={last_model}: {last_error}）"
        )

    def _iter_stream(
        self, provider_name: str, model: str, stream: Any, started: float
    ) -> Iterator[str]:
        """消费已建立的流：逐片段 yield 文本；结束时尽力累加 usage 并打日志。"""
        usage: dict[str, int] | None = None
        try:
            for chunk in stream:
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage is not None:  # include_usage 时 usage 在最终 chunk
                    usage = {
                        "prompt_tokens": int(getattr(chunk_usage, "prompt_tokens", 0) or 0),
                        "completion_tokens": int(getattr(chunk_usage, "completion_tokens", 0) or 0),
                        "total_tokens": int(getattr(chunk_usage, "total_tokens", 0) or 0),
                    }
                choices = getattr(chunk, "choices", None)
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                piece = getattr(delta, "content", None) if delta is not None else None
                if piece:
                    yield piece
        except Exception as exc:
            raise LLMError(
                f"流式输出中途失败（provider={provider_name} model={model}）: {exc}"
            ) from exc

        if usage is not None:
            for key, value in usage.items():
                self.total_usage[key] += value
        logger.info(
            "llm_stream_ok provider=%s model=%s elapsed_ms=%d prompt_tokens=%d completion_tokens=%d total_tokens=%d",
            provider_name,
            model,
            int((time.perf_counter() - started) * 1000),
            usage["prompt_tokens"] if usage else 0,
            usage["completion_tokens"] if usage else 0,
            usage["total_tokens"] if usage else 0,
        )

    def _to_response(self, provider_name: str, model: str, raw: Any, started: float) -> LLMResponse:
        """把 SDK 返回对象归一化为 LLMResponse，累加 usage 并打结构化日志。"""
        choices = getattr(raw, "choices", None)
        message = choices[0].message if choices else None
        content = getattr(message, "content", None) if message is not None else None

        tool_calls: list[dict[str, Any]] | None = None
        raw_tools = getattr(message, "tool_calls", None) if message is not None else None
        if raw_tools:
            tool_calls = [
                {
                    "id": getattr(tc, "id", None),
                    "type": getattr(tc, "type", "function"),
                    "function": {
                        "name": getattr(getattr(tc, "function", None), "name", None),
                        "arguments": getattr(getattr(tc, "function", None), "arguments", None),
                    },
                }
                for tc in raw_tools
            ]

        usage: dict[str, int] | None = None
        raw_usage = getattr(raw, "usage", None)
        if raw_usage is not None:
            usage = {
                "prompt_tokens": int(getattr(raw_usage, "prompt_tokens", 0) or 0),
                "completion_tokens": int(getattr(raw_usage, "completion_tokens", 0) or 0),
                "total_tokens": int(getattr(raw_usage, "total_tokens", 0) or 0),
            }
            for key, value in usage.items():
                self.total_usage[key] += value

        logger.info(
            "llm_chat_ok provider=%s model=%s elapsed_ms=%d prompt_tokens=%d completion_tokens=%d total_tokens=%d",
            provider_name,
            model,
            int((time.perf_counter() - started) * 1000),
            usage["prompt_tokens"] if usage else 0,
            usage["completion_tokens"] if usage else 0,
            usage["total_tokens"] if usage else 0,
        )
        return LLMResponse(content=content, tool_calls=tool_calls, usage=usage, provider=provider_name)
