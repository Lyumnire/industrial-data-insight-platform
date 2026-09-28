# AI-assisted
"""SQL 校验器（红线 R9）：sqlglot AST 白名单 + 强制 LIMIT + 禁多语句。

校验规则（docs/plans/2026-09-19-P1-走通骨架.md §Task 4 / docs/03 §3.3 A4）：
1. 空串拒绝；
2. 注释内藏分号拒绝（词法扫描兜底——sqlglot 会丢弃注释，仅靠 AST 会漏放）；
3. sqlglot.parse 解析失败 → SQLValidationError([语法错误])；
4. 仅允许单条语句；
5. walk 遍历禁止 DML/DDL/权限/多语句载体节点；
6. 根节点仅允许 exp.Select / exp.Union（WITH-CTE 挂在 Select 上，天然放行）；
7. LIMIT 归一化：已有更小 LIMIT 保留，无或更大收紧为 max_limit；
   Union 根先剥掉旧外层 LIMIT 再包子查询补 LIMIT（避免 LIMIT 归属歧义）。
返回 mysql 方言化 SQL 字符串。

注：sqlglot 30.x 已将 TRUNCATE 节点更名为 exp.TruncateTable（无 exp.Truncate），
FORBIDDEN 按名称动态构建以兼容（探针验证：sqlglot 30.18.0）。
"""
from __future__ import annotations

import logging

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

logger = logging.getLogger("a07.sqlguard")

__all__ = ["FORBIDDEN", "SQLValidationError", "validate_sql"]


class SQLValidationError(RuntimeError):
    """SQL 未通过白名单校验（与 app 现有 LLMNotConfiguredError 同风格：RuntimeError 子类）。"""


# walk 阶段禁止出现的节点类型。exp.Truncate 在 30.x 不存在，追加 TruncateTable。
_FORBIDDEN_NAMES = (
    "Insert", "Update", "Delete", "Drop", "Alter", "Create", "Truncate",
    "Grant", "Revoke", "Command", "Into", "Merge", "TruncateTable",
)
FORBIDDEN: tuple[type[exp.Expression], ...] = tuple(
    getattr(exp, name) for name in _FORBIDDEN_NAMES if hasattr(exp, name)
)

_UNION_WRAP_ALIAS = "_a07_union"


def _comment_hides_semicolon(sql: str) -> bool:
    """词法扫描：注释（-- / # / /* */）内是否含分号。

    字符串/反引号标识符内的分号不算（含 MySQL 反斜杠转义）；
    多语句本身由 parse 的语句计数拦截，这里只兜注释。
    """
    i, n = 0, len(sql)
    state = "code"  # code | line_comment | block_comment
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if state == "code":
            if ch in ("'", '"', "`"):
                i = _skip_quoted(sql, i, ch)
                continue
            if ch == "-" and nxt == "-":
                state = "line_comment"
                i += 2
                continue
            if ch == "#":
                state = "line_comment"
                i += 1
                continue
            if ch == "/" and nxt == "*":
                state = "block_comment"
                i += 2
                continue
        elif state == "line_comment":
            if ch == "\n":
                state = "code"
            elif ch == ";":
                return True
        else:  # block_comment
            if ch == "*" and nxt == "/":
                state = "code"
                i += 2
                continue
            if ch == ";":
                return True
        i += 1
    return False


def _skip_quoted(sql: str, start: int, quote: str) -> int:
    """返回引号闭合位置之后的小标；未闭合则返回串尾（交给 parse 报语法错）。"""
    i = start + 1
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "\\":
            i += 2
            continue
        if ch == quote:
            return i + 1
        i += 1
    return n


def _current_limit_value(root: exp.Expression) -> int | None:
    """读取根节点已有 LIMIT 的整数值；非数字字面量（如 LIMIT ?）返回 None 视为需收紧。"""
    limit_node = root.args.get("limit")
    if limit_node is None:
        return None
    try:
        return int(limit_node.expression.name)
    except (AttributeError, ValueError):
        return None


def _normalize_limit(root: exp.Expression, max_limit: int) -> exp.Expression:
    """LIMIT 归一化：更小保留；无/更大/非字面量收紧为 max_limit；Union 包子查询。"""
    current = _current_limit_value(root)
    if current is not None and current <= max_limit:
        return root
    if isinstance(root, exp.Union):
        root.args.pop("limit", None)  # 收紧时剥掉旧外层 LIMIT，避免双 LIMIT 叠加
        wrapped = exp.select("*").from_(root.subquery(_UNION_WRAP_ALIAS))
        return wrapped.limit(max_limit)
    return root.limit(max_limit)


def validate_sql(sql: str, dialect: str = "mysql", max_limit: int = 500) -> str:
    """白名单校验并归一化 LIMIT，返回方言化 SQL 字符串；不合规抛 SQLValidationError。

    消息统一以 [原因类别] 前缀开头（空SQL/注释内含分号/语法错误/多语句/
    禁止语句/非查询语句），供上层与测试识别（docs/03 §6 错误处理）。
    """
    if not isinstance(sql, str) or not sql.strip():
        raise SQLValidationError("[空SQL] 语句为空")

    if _comment_hides_semicolon(sql):
        raise SQLValidationError("[注释内含分号] 注释中不允许出现分号（防跨方言注入）")

    try:
        parsed = sqlglot.parse(sql, read=dialect)
    except ParseError as exc:
        logger.warning("sql_parse_error dialect=%s error=%s", dialect, str(exc)[:200])
        raise SQLValidationError(f"[语法错误] SQL 解析失败: {str(exc)[:200]}") from exc
    except sqlglot.errors.SqlglotError as exc:  # tokenize 等其他解析器内部错误同样拒绝
        raise SQLValidationError(f"[语法错误] SQL 解析失败: {str(exc)[:200]}") from exc

    stmts = [s for s in parsed if s is not None]
    if not stmts:
        raise SQLValidationError("[空SQL] 语句为空")
    if len(stmts) > 1:
        raise SQLValidationError(f"[多语句] 仅允许单条查询语句，实际 {len(stmts)} 条")

    root = stmts[0]
    # 先 walk 白名单（能给出具体节点名），再查根类型（兜 SHOW/SET 等非查询根）
    for node in root.walk():
        if isinstance(node, FORBIDDEN):
            raise SQLValidationError(f"[禁止语句] 不允许的语句类型: {type(node).__name__}")
    if not isinstance(root, (exp.Select, exp.Union)):
        raise SQLValidationError(
            f"[非查询语句] 仅允许 SELECT/UNION（含 WITH-CTE），实际: {type(root).__name__}"
        )

    return _normalize_limit(root, max_limit).sql(dialect=dialect)
