# AI-assisted
"""A1 引擎 API 路由（docs/03 §3.3 A1、§4 事件协议 / P1 计划 §Task 5 Step 5.4）。

- POST /api/agent/analyze：SSE 流式返回（text/event-stream），逐帧透传 pipeline 产出，
  代理层不解析改写（契约纪律）；任何漏网异常以 error 帧收尾，SSE 流永不裸崩。
- POST /internal/reindex：P1 = 重新加载 corpus.json（P2 升级为重建向量索引），
  返回 {tables, metrics, examples} 数量。
- 权限：引擎不鉴权（仅内网可达，docs/03 §6），由 a07-server 代理层完成 JWT 校验。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.llm.client import LLMClient
from app.ml.contracts import MLRequest
from app.ml.modeler import MLDataError, ml_payload, run_ml
from app.orchestrator.pipeline import run_analysis
from app.retriever import DEFAULT_CORPUS_PATH, Retriever
from app.schemas.event import SSEEvent

logger = logging.getLogger("a07.api")

router = APIRouter()

# 进程级单例：引擎无状态（不存用户态），仅缓存 LLM 客户端与语料索引
_llm = LLMClient(get_settings())
_retriever = Retriever(DEFAULT_CORPUS_PATH)


def get_llm() -> LLMClient:
    return _llm


def get_retriever() -> Retriever:
    return _retriever


class AnalyzeRequest(BaseModel):
    """POST /api/agent/analyze 请求体（docs/03 §4）。"""

    sessionId: str = ""
    messageId: str = ""
    question: str
    history: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/api/agent/analyze")
async def analyze(req: AnalyzeRequest) -> StreamingResponse:
    """发起分析：返回 text/event-stream，逐帧产出 docs/03 §4 协议事件。"""

    async def stream() -> Any:
        try:
            async for frame in run_analysis(req, get_llm(), get_retriever(), get_settings()):
                yield frame
        except Exception as exc:  # 双保险：pipeline 已兜底，这里防路由层意外
            logger.exception("analyze_stream_unhandled sessionId=%s error=%s", req.sessionId, exc)
            yield SSEEvent(
                type="error",
                data={
                    "code": "INTERNAL_ERROR",
                    "message": "服务内部错误，请稍后重试或联系管理员",
                    "suggestion": "请重新发起分析；若持续失败请联系管理员查看引擎日志",
                },
            ).to_sse_frame()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 关闭 nginx 缓冲，保证逐帧下发
        },
    )


@router.post("/internal/reindex")
def reindex() -> dict[str, int]:
    """重建检索索引：P1 重新加载 corpus.json，返回各 collection 数量。"""
    logger.info("reindex_requested source=api")
    return get_retriever().reload()


# ---- A7 建模工作台直调接口（P2a §Task 12.4，T-012）----


class MlRunRequest(MLRequest):
    """POST /api/agent/ml/run 请求体 = 统一 MLRequest 契约 + question（记录用，可空）。"""

    question: str = ""


@router.post("/api/agent/ml/run")
def ml_run(req: MlRunRequest) -> dict[str, Any]:
    """内部 REST：按统一 ML 契约执行一次建模（同一沙箱链路，模型持久化到 models/）。

    data_ref 支持 只读 SELECT SQL（经 sqlguard 校验 + 只读账号执行）或 CSV 路径；
    数据不足/列不存在等前置校验失败返回 400 + 用户可读 message（docs/03 §6）。
    def 端点由 FastAPI 放入线程池执行，不阻塞事件循环。
    """
    logger.info(
        "ml_run_requested model_type=%s features=%s target=%s",
        req.model_type, req.features, req.target,
    )
    try:
        resp = run_ml(req)
    except MLDataError as exc:
        logger.warning("ml_run_rejected model_type=%s error=%s", req.model_type, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ml_payload(resp)
