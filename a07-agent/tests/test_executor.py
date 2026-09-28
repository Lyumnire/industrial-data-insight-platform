# AI-assisted
"""T-004 只读执行器单元测试（TDD 先行）。

全部 mock pymysql.connect（不触真实 DB）：
- 正常返回组装（DictCursor / read_timeout=sql_timeout_seconds*1000）；
- 行数超 max_limit 截断且 truncated=True；
- 连接异常包装为 SQLExecutionError（红线 R8：异常不裸吞）；
- 每次执行（成败皆）写审计 jsonl（tmp_path 注入，红线 R8 结构化日志）。
真实库冒烟用例需显式 MYSQLSMOKE=1 才运行（Docker/凭据未就绪时跳过）。
"""
from __future__ import annotations

import json
import os
from typing import Any

import pymysql
import pytest

from app.config import Settings
from app.sqlguard import SQLExecutionError, execute_readonly

# 屏蔽本机环境变量，保证测试读的是显式构造的 cfg
_ENV_KEYS = (
    "MYSQL_HOST", "MYSQL_PORT", "MYSQL_DB", "MYSQL_USER", "MYSQL_PASSWORD",
    "MYSQL_READONLY_USER", "MYSQL_READONLY_PASSWORD", "SQL_MAX_LIMIT", "SQL_TIMEOUT_SECONDS",
)


@pytest.fixture(autouse=True)
def _isolate_db_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_KEYS:
        monkeypatch.delenv(name, raising=False)


def _make_cfg(**overrides: Any) -> Settings:
    values: dict[str, Any] = dict(
        _env_file=None,
        mysql_host="db.test",
        mysql_port=3307,
        mysql_db="mes_demo",
        mysql_readonly_user="mes_readonly",
        mysql_readonly_password="pw-placeholder",
        sql_timeout_seconds=7,
        sql_max_limit=500,
    )
    values.update(overrides)
    return Settings(**values)


def _install_fake_db(
    monkeypatch: pytest.MonkeyPatch,
    columns: list[str],
    rows: list[dict[str, Any]],
    connect_error: Exception | None = None,
) -> dict[str, Any]:
    """替换 pymysql.connect 为假实现；captured 记录连接参数与执行 SQL。"""
    captured: dict[str, Any] = {}

    class _FakeCursor:
        def __init__(self) -> None:
            self.description = [(c, None, None, None, None, None, None) for c in columns]

        def __enter__(self) -> "_FakeCursor":
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def execute(self, sql: str) -> None:
            captured["executed_sql"] = sql

        def fetchall(self) -> list[dict[str, Any]]:
            return [dict(r) for r in rows]

    class _FakeConnection:
        def cursor(self, *args: Any, **kwargs: Any) -> _FakeCursor:
            captured["cursor_args"] = (args, kwargs)
            return _FakeCursor()

        def close(self) -> None:
            captured["closed"] = True

    def fake_connect(**kwargs: Any) -> _FakeConnection:
        captured["kwargs"] = kwargs
        if connect_error is not None:
            raise connect_error
        return _FakeConnection()

    monkeypatch.setattr("pymysql.connect", fake_connect)
    return captured


def test_normal_result_assembly(monkeypatch: pytest.MonkeyPatch) -> None:
    """正常路径：列名/行/行数组装正确，连接参数来自 cfg（R1 只读账号 + R8 超时）。"""
    rows = [
        {"production_line": "L1", "total": 10},
        {"production_line": "L2", "total": 20},
        {"production_line": "L3", "total": 30},
    ]
    captured = _install_fake_db(monkeypatch, ["production_line", "total"], rows)
    cfg = _make_cfg()

    result = execute_readonly("SELECT production_line, COUNT(*) AS total FROM process_output", cfg)

    assert result.columns == ["production_line", "total"]
    assert result.rows == rows
    assert result.rowcount == 3
    assert result.truncated is False
    assert result.elapsed_ms >= 0
    assert captured["executed_sql"].startswith("SELECT")
    assert captured["closed"] is True
    kw = captured["kwargs"]
    assert kw["host"] == "db.test" and kw["port"] == 3307 and kw["database"] == "mes_demo"
    assert kw["user"] == "mes_readonly" and kw["password"] == "pw-placeholder"
    assert kw["read_timeout"] == 7 * 1000  # sql_timeout_seconds * 1000
    assert kw["cursorclass"] is pymysql.cursors.DictCursor


def test_over_limit_rows_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    """行数 > cfg.sql_max_limit：rows 截到上限、rowcount 保留总数、truncated=True。"""
    rows = [{"id": i} for i in range(5)]
    _install_fake_db(monkeypatch, ["id"], rows)
    cfg = _make_cfg(sql_max_limit=3)

    result = execute_readonly("SELECT id FROM t", cfg)

    assert result.truncated is True
    assert result.rows == [{"id": 0}, {"id": 1}, {"id": 2}]
    assert result.rowcount == 5  # 总行数不因截断丢失


def test_connect_error_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    """连接失败包装为 SQLExecutionError，且保留原始异常为 __cause__。"""
    err = pymysql.err.OperationalError(2003, "Can't connect to MySQL server")
    _install_fake_db(monkeypatch, [], [], connect_error=err)

    with pytest.raises(SQLExecutionError) as excinfo:
        execute_readonly("SELECT 1", _make_cfg())

    assert "OperationalError" in str(excinfo.value) or "Can't connect" in str(excinfo.value)
    assert excinfo.value.__cause__ is err


def test_audit_written_on_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """成功执行也写审计（ts/sql/valid/elapsed_ms/rowcount/error 齐全）。"""
    _install_fake_db(
        monkeypatch, ["id"], [{"id": 1}, {"id": 2}, {"id": 3}]
    )
    audit_file = tmp_path / "nested" / "sql_audit.jsonl"

    execute_readonly("SELECT id FROM t", _make_cfg(), audit_path=audit_file)

    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["sql"] == "SELECT id FROM t"
    assert record["valid"] is True
    assert record["rowcount"] == 3
    assert record["error"] is None
    assert record["elapsed_ms"] >= 0
    assert record["ts"]


def test_audit_written_on_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """失败执行同样落审计：valid=False，error 含原始异常信息（R8 结构化日志）。"""
    _install_fake_db(
        monkeypatch, [], [], connect_error=pymysql.err.OperationalError(2003, "Can't connect")
    )
    audit_file = tmp_path / "sql_audit.jsonl"

    with pytest.raises(SQLExecutionError):
        execute_readonly("SELECT 1", _make_cfg(), audit_path=audit_file)

    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["valid"] is False
    assert "Can't connect" in record["error"]
    assert record["rowcount"] is None


@pytest.mark.skipif(
    os.environ.get("MYSQLSMOKE") != "1",
    reason="真实库冒烟：需本机 MySQL 与 .env 只读凭据就绪（设 MYSQLSMOKE=1 开启）",
)
def test_real_db_smoke() -> None:
    """实库连通验证（Docker MySQL + mes_demo 就绪后手动开启）。"""
    from app.sqlguard import validate_sql

    cfg = Settings()
    sql = validate_sql(
        "SELECT production_line, COUNT(*) AS total FROM process_output GROUP BY production_line"
    )
    result = execute_readonly(sql, cfg)
    assert result.rowcount <= cfg.sql_max_limit
    assert set(result.columns) == {"production_line", "total"}
