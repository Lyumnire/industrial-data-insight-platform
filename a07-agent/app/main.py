# AI-assisted
"""A1 引擎 API 骨架：/health + CORS + 全局异常处理器。

P1 仅骨架：`POST /api/agent/analyze`（SSE）由 Task 5 的 app/api/routes.py 挂载；
本文件保持薄壳（红线 R6：逻辑不堆 main.py）。异常统一 {code,message}（红线 R8），
内部细节只进结构化日志、不外泄给客户端。
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import get_retriever, router as api_router
from app.config import get_settings

APP_VERSION = "0.1.0"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("a07.main")

_settings = get_settings()
logger.info(
    "agent_engine_boot version=%s agent_port=%s sql_max_limit=%s "
    "sql_timeout_seconds=%s sandbox_timeout_seconds=%s",
    APP_VERSION,
    _settings.agent_port,
    _settings.sql_max_limit,
    _settings.sql_timeout_seconds,
    _settings.sandbox_timeout_seconds,
)

app = FastAPI(title="A07 Agent Engine", version=APP_VERSION)

# 前端开发服务器(5173)与业务底座 a07-server(8080) 的跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8080"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# 业务路由：/api/agent/analyze（SSE）+ /internal/reindex（T-005）
app.include_router(api_router)


@app.get("/health")
def health() -> dict[str, str | bool]:
    # corpus_loaded：A3 检索器语料加载状态（T-005 起如实反映，不再占位 False）
    return {"status": "ok", "version": APP_VERSION, "corpus_loaded": get_retriever().loaded}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unhandled_error path=%s method=%s error=%s", request.url.path, request.method, exc
    )
    return JSONResponse(
        status_code=500,
        content={"code": "INTERNAL_ERROR", "message": "服务内部错误，请稍后重试或联系管理员"},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    logger.warning(
        "request_validation_error path=%s errors=%s", request.url.path, exc.errors()
    )
    return JSONResponse(
        status_code=422,
        content={"code": "VALIDATION_ERROR", "message": "请求参数不合法"},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    logger.warning(
        "http_error path=%s status=%d detail=%s",
        request.url.path,
        exc.status_code,
        exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": f"HTTP_{exc.status_code}", "message": str(exc.detail)},
    )
