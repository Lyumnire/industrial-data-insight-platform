# AI-assisted
"""T-004 SQL 校验器单元测试（TDD 先行）。

覆盖 docs/plans/2026-09-19-P1-走通骨架.md §Task 4 用例清单：
合法放行（普通 SELECT / WITH-CTE / 保留已有小 LIMIT）、自动补 LIMIT、
拒绝清单（DML/DDL/权限/多语句/INTO OUTFILE/注释藏分号/语法错/非查询/空串），
并断言失败信息含原因类别（红线 R9：AST 白名单 + 强制 LIMIT + 禁多语句）。
"""
from __future__ import annotations

import pytest

from app.sqlguard import SQLValidationError, validate_sql

# ---- 合法放行 ----


def test_plain_select_passes() -> None:
    """普通 SELECT 原样通过并返回方言化 SQL 字符串。"""
    sql = "SELECT * FROM process_output WHERE production_line = 'L1'"
    out = validate_sql(sql)
    assert isinstance(out, str)
    assert out.upper().startswith("SELECT")
    assert "process_output" in out


def test_cte_select_passes() -> None:
    """WITH cte AS (...) SELECT ... 放行（CTE 挂在 Select 上）。"""
    out = validate_sql("WITH cte AS (SELECT 1 AS x) SELECT * FROM cte")
    assert out.upper().startswith("WITH")
    assert "LIMIT 500" in out  # CTE 主体同样强制 LIMIT


def test_existing_smaller_limit_preserved() -> None:
    """已带 LIMIT 300（< max_limit）保留原值，不收紧到 500。"""
    sql = (
        "SELECT production_line, COUNT(*) AS c FROM process_output "
        "GROUP BY production_line ORDER BY c DESC LIMIT 300"
    )
    out = validate_sql(sql)
    assert "LIMIT 300" in out
    assert "LIMIT 500" not in out


def test_existing_limit_equal_to_max_kept() -> None:
    """LIMIT 恰等于 max_limit 时保留，不重复追加。"""
    out = validate_sql("SELECT * FROM t LIMIT 500")
    assert out.count("LIMIT") == 1 and "LIMIT 500" in out


def test_union_keeps_small_limit() -> None:
    """UNION 已带小 LIMIT 原样保留。"""
    out = validate_sql("SELECT 1 UNION SELECT 2 LIMIT 10")
    assert "LIMIT 10" in out


# ---- 自动补 LIMIT ----


def test_missing_limit_added() -> None:
    """无 LIMIT 的 SELECT 校验后含 LIMIT 500（默认 max_limit）。"""
    out = validate_sql("SELECT * FROM process_output")
    assert "LIMIT 500" in out


def test_bigger_limit_tightened() -> None:
    """已有 LIMIT 大于 max_limit 时收紧为 500。"""
    out = validate_sql("SELECT * FROM process_output LIMIT 100000")
    assert "LIMIT 500" in out
    assert "100000" not in out


def test_custom_max_limit() -> None:
    """max_limit 参数生效：LIMIT 收紧为 50。"""
    out = validate_sql("SELECT * FROM process_output LIMIT 100000", max_limit=50)
    assert "LIMIT 50" in out


def test_union_without_limit_wrapped_and_capped() -> None:
    """无 LIMIT 的 UNION 包子查询后再补 LIMIT（避免 LIMIT 归属歧义）。"""
    out = validate_sql("SELECT 1 UNION SELECT 2")
    assert out.upper().startswith("SELECT * FROM (")
    assert "UNION" in out
    assert "LIMIT 500" in out


# ---- 合法边界（不应误伤）----


def test_benign_comment_without_semicolon_passes() -> None:
    """普通注释（无分号）不拦截。"""
    out = validate_sql("SELECT * FROM t -- 查询全部产线")
    assert "SELECT" in out


def test_semicolon_inside_string_literal_passes() -> None:
    """字符串字面量里的分号不算多语句。"""
    out = validate_sql("SELECT ';' AS semicolon_in_string")
    assert "semicolon_in_string" in out


# ---- 拒绝清单：参数化，失败信息必须含原因类别 ----

# (sql, 期望原因类别)。类别与 validator 抛错前缀一一对应。
_REJECT_CASES: list[tuple[str, str]] = [
    # DML / DDL / 权限类（AST 白名单外，walk 阶段拦截）
    ("INSERT INTO t VALUES (1)", "禁止语句"),
    ("UPDATE t SET produced_qty = 0", "禁止语句"),
    ("DELETE FROM process_output", "禁止语句"),
    ("DROP TABLE process_output", "禁止语句"),
    ("ALTER TABLE t ADD COLUMN c INT", "禁止语句"),
    ("CREATE TABLE t (id INT)", "禁止语句"),
    ("TRUNCATE TABLE t", "禁止语句"),
    ("GRANT ALL ON *.* TO u", "禁止语句"),
    ("REVOKE ALL ON *.* FROM u", "禁止语句"),
    # 多语句
    ("SELECT 1; DROP TABLE x", "多语句"),
    ("SELECT 1; SELECT 2", "多语句"),
    # 文件写出 / 语法错误
    ("SELECT * FROM t INTO OUTFILE '/x'", "语法错误"),
    ("SELECT * FROM(真·语法错", "语法错误"),
    # 注释内藏分号（解析为单条合法 SELECT，需词法扫描兜底）
    ("SELECT 1 /* ; DROP TABLE t */", "注释内含分号"),
    ("SELECT 1 -- ; DELETE FROM t", "注释内含分号"),
    # 非查询语句（SHOW/SET 等，根节点非 SELECT/UNION）
    ("SHOW TABLES", "非查询语句"),
    ("SET NAMES utf8mb4", "非查询语句"),
    # 空串 / 纯空白 / 只有分号
    ("", "空SQL"),
    ("   ", "空SQL"),
    (";;", "空SQL"),
]


@pytest.mark.parametrize(("sql", "category"), _REJECT_CASES)
def test_rejects_with_category(sql: str, category: str) -> None:
    """拒绝清单逐条抛 SQLValidationError，且消息含原因类别前缀。"""
    with pytest.raises(SQLValidationError) as excinfo:
        validate_sql(sql)
    message = str(excinfo.value)
    assert category in message, f"期望类别 {category!r} 未出现在错误信息: {message!r}"
