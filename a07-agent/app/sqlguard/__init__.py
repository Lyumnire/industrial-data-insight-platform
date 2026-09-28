# AI-assisted
"""A4/A5 SQL 校验与只读执行（sqlguard）。

对外暴露：validate_sql / SQLValidationError（校验器）、
execute_readonly / ExecResult / SQLExecutionError（执行器）。
"""
from __future__ import annotations

from app.sqlguard.executor import (
    DEFAULT_AUDIT_PATH,
    ExecResult,
    SQLExecutionError,
    execute_readonly,
)
from app.sqlguard.validator import FORBIDDEN, SQLValidationError, validate_sql

__all__ = [
    "DEFAULT_AUDIT_PATH",
    "FORBIDDEN",
    "ExecResult",
    "SQLExecutionError",
    "SQLValidationError",
    "execute_readonly",
    "validate_sql",
]
