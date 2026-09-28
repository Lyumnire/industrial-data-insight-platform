# AI-assisted
"""只读执行器（docs/03 §3.3 A5 / 红线 R1+R8）。

约定：入参 SQL 必须先经 validate_sql 白名单校验（编排器 Task 5 负责串接；
本模块不做二次校验，保持单一职责）。连接参数全部来自 cfg（只读账号，
红线 R1：引擎不持有管理员凭据），read_timeout=sql_timeout_seconds*1000，
DictCursor 取数；行数超 cfg.sql_max_limit 时截断并置 truncated=True
（rowcount 仍保留总行数，供"已截断"提示用，docs/03 §6 行数过大行）。

执行审计（红线 R8 结构化日志）：每次执行（成败皆）追加一行 JSON 到
logs/sql_audit.jsonl（目录自动创建；logs/ 已在 .gitignore）。审计写失败
仅记 warning 不影响主流程。字段：{ts, sql, valid, elapsed_ms, rowcount, error}。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pymysql
import pymysql.cursors

from app.config import Settings

logger = logging.getLogger("a07.sqlguard")

__all__ = ["DEFAULT_AUDIT_PATH", "ExecResult", "SQLExecutionError", "execute_readonly"]

# a07-agent/app/sqlguard/executor.py -> parents[2] = a07-agent
DEFAULT_AUDIT_PATH = Path(__file__).resolve().parents[2] / "logs" / "sql_audit.jsonl"

_audit_lock = threading.Lock()


class SQLExecutionError(RuntimeError):
    """SQL 执行失败（连接/超时/服务端报错等），与现有异常体系一致（RuntimeError 子类）。"""


@dataclass
class ExecResult:
    """执行结果：rows 为截断后给后端的行（前端再截 100），rowcount 为 fetch 总行数。"""

    columns: list[str]
    rows: list[dict[str, Any]]
    rowcount: int
    elapsed_ms: float
    truncated: bool


def execute_readonly(sql: str, cfg: Settings, *, audit_path: str | Path | None = None) -> ExecResult:
    """用只读账号执行单条 SQL 并返回 ExecResult；失败包装为 SQLExecutionError。

    audit_path 仅供测试注入 tmp_path；生产走 DEFAULT_AUDIT_PATH。
    """
    audit_file = Path(audit_path) if audit_path is not None else DEFAULT_AUDIT_PATH
    start = time.perf_counter()
    rowcount: int | None = None
    error: str | None = None
    try:
        result = _execute(sql, cfg)
        rowcount = result.rowcount
        result.elapsed_ms = (time.perf_counter() - start) * 1000
        return result
    except Exception as exc:  # 统一包装上抛，不吞异常（红线 R8）
        error = f"{type(exc).__name__}: {exc}"
        raise SQLExecutionError(f"[执行失败] {type(exc).__name__}: {exc}") from exc
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        _append_audit(
            audit_file,
            {
                "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "sql": sql,
                "valid": error is None,
                "elapsed_ms": round(elapsed_ms, 3),
                "rowcount": rowcount,
                "error": error,
            },
        )


def _execute(sql: str, cfg: Settings) -> ExecResult:
    """建立只读连接取数并组装 ExecResult（LIMIT 截断在此落地）。"""
    conn = pymysql.connect(
        host=cfg.mysql_host,
        port=cfg.mysql_port,
        database=cfg.mysql_db,
        user=cfg.mysql_readonly_user,  # 红线 R1：仅只读账号
        password=cfg.mysql_readonly_password,
        charset="utf8mb4",
        read_timeout=cfg.sql_timeout_seconds * 1000,
        write_timeout=cfg.sql_timeout_seconds * 1000,
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            fetched = [dict(row) for row in cursor.fetchall()]
            description = cursor.description
    finally:
        conn.close()

    columns = [col[0] for col in description] if description else []
    total = len(fetched)
    truncated = total > cfg.sql_max_limit
    rows = fetched[: cfg.sql_max_limit] if truncated else fetched
    return ExecResult(columns=columns, rows=rows, rowcount=total, elapsed_ms=0.0, truncated=truncated)


def _append_audit(path: Path, record: dict[str, Any]) -> None:
    """审计 jsonl 追加一行；写失败只告警不抛出（审计不应阻断查询主流程）。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _audit_lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("audit_write_failed path=%s error=%s", path, exc)
