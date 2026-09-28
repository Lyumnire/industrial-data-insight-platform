# AI-assisted
"""ECharts option 后端模板拼装（docs/02 §1.5 / docs/03 §3.3 A6 图表部分）。

硬性约定（ADR）：图表 option 一律由本模块按结果集程序化拼装，**禁止 LLM 生成 option**；
支持 line/bar/pie/scatter 四类模板。所有列值经归一化（Decimal→float、日期→ISO 字符串、
数值字符串→数值），保证 json.dumps 可序列化且数值轴可用。

`build_chart_option(chart_type, columns, rows, x=None, y=None)` 签名为编排层稳定契约；
无法出图（类型不支持/无数据/无可用数值列）返回 None，由编排层决定跳过图表。
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

SUPPORTED_CHART_TYPES: tuple[str, ...] = ("line", "bar", "pie", "scatter")

_DATE_NAME_HINTS = ("date", "time", "month", "week", "day", "日期", "时间", "月份")
_DATE_VALUE_RE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}")

_TITLE_MAX_LEN = 30

# BUG-018 / T-028：bar 稀疏多系列回退阈值——系列数≈类目数且每系列非空点极少
# （典型：x=product_id, series_field=product_name，一行一品 → 一柱一空系列）。
_SPARSE_SERIES_RATIO = 0.8
_SPARSE_AVG_NON_NULL = 1.5


def truncate_title(text: str, limit: int = _TITLE_MAX_LEN) -> str:
    """标题取 expected_output 截断：压空白、超长加省略号。"""
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return "分析图表"
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


def _as_label(value: Any) -> str:
    """坐标轴/扇区标签：一切归一化为字符串（防 Decimal/日期不可序列化）。"""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return f"{value:g}"
    return str(value)


def _as_number(value: Any) -> int | float | None:
    """序列值：尽量转为数值（数值轴/扇区值），失败返回 None。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text) if re.fullmatch(r"-?\d+", text) else float(text)
        except ValueError:
            return None
    return None


def numeric_columns(columns: list[str], rows: list[dict[str, Any]]) -> list[str]:
    """取"几乎全为数值"的列（全部非空值均可转数值）。"""
    result: list[str] = []
    for col in columns:
        values = [row.get(col) for row in rows]
        non_null = [v for v in values if v is not None]
        if non_null and all(_as_number(v) is not None for v in non_null):
            result.append(col)
    return result


def _chart_grid(*, has_legend: bool = False, with_axis: bool = True) -> dict[str, Any]:
    """ECharts grid 留白（BUG-018 / T-028）。

    top 预留 title（居中 ~30-40px）+ legend（top:28 时再叠一行高度）；
    bottom 预留 x 轴名；containLabel 保证刻度标签不贴边。
    """
    if not with_axis:
        # pie：无坐标轴，但仍需给 title/legend/扇区标签留白
        return {"top": 88 if has_legend else 56, "bottom": 40, "left": 24, "right": 24, "containLabel": True}
    return {
        "top": 88 if has_legend else 56,
        "bottom": 52,
        "left": 56,
        "right": 32,
        "containLabel": True,
    }


def _is_degenerate_bar_grouping(
    ctype: str,
    x: str,
    y_col: str,
    series_field: str,
    rows: list[dict[str, Any]],
) -> bool:
    """bar 图：系列数≈类目数且每系列非空点极少 → 应回退单系列（BUG-018）。

    典型误伤：x=product_id、series_field=product_name——一行一品，每系列仅 1 个
    非空点、系列数等于类目数，ECharts 多系列柱与 x 轴类别错位且 legend 冗长。
    真正的多系列趋势（如产线×日期）每系列多点，不会触发回退。
    """
    if (ctype or "").lower() != "bar":
        return False
    categories = {_as_label(row.get(x)) for row in rows}
    groups: dict[str, int] = {}
    for row in rows:
        group = _as_label(row.get(series_field))
        groups[group] = groups.get(group, 0) + (1 if _as_number(row.get(y_col)) is not None else 0)
    n_series = len(groups)
    n_cats = len(categories)
    if n_series < 2 or n_cats < 2:
        return False
    if n_series < max(2, math.ceil(n_cats * _SPARSE_SERIES_RATIO)):
        return False
    avg_non_null = sum(groups.values()) / n_series
    return avg_non_null <= _SPARSE_AVG_NON_NULL


def _date_column(columns: list[str], rows: list[dict[str, Any]]) -> str | None:
    """识别日期列：列名暗示优先，其次按值形态（YYYY-MM-DD...）。"""
    for col in columns:
        lower = col.lower()
        if any(hint in lower or hint in col for hint in _DATE_NAME_HINTS):
            return col
    for col in columns:
        samples = [row.get(col) for row in rows if row.get(col) is not None][:5]
        if samples and all(
            isinstance(v, (datetime, date)) or (isinstance(v, str) and _DATE_VALUE_RE.match(v))
            for v in samples
        ):
            return col
    return None


def pick_axes(
    chart_type: str, columns: list[str], rows: list[dict[str, Any]]
) -> tuple[str | None, list[str]]:
    """按图表类型挑 x/y：line 优先日期列作 x，bar/pie 取首个分类列，scatter 取两个数值列。"""
    numeric = numeric_columns(columns, rows)
    categorical = [c for c in columns if c not in numeric]
    ctype = (chart_type or "").lower()

    if ctype == "scatter":
        if len(numeric) >= 2:
            return numeric[0], [numeric[1]]
        return (columns[0] if columns else None), [numeric[0]] if numeric else []

    if ctype == "line":
        x = _date_column(columns, rows) or (categorical[0] if categorical else (columns[0] if columns else None))
    else:
        x = categorical[0] if categorical else (columns[0] if columns else None)
    y_list = [c for c in numeric if c != x][:4]
    if ctype == "pie":
        y_list = y_list[:1]
    return x, y_list


def build_chart_option(
    chart_type: str,
    columns: list[str],
    rows: list[dict[str, Any]],
    x: str | None = None,
    y: str | list[str] | None = None,
    series_field: str | None = None,
) -> dict[str, Any] | None:
    """按模板拼装 ECharts option；不支持类型/空数据/无数值列时返回 None。

    x/y 缺省时由 pick_axes 自动选择；标题默认取 y 列名，编排层会用
    expected_output 截断后覆盖 option["title"]["text"]。
    line/bar 图可传 series_field（结果集中某一分类列）：按该列值分组，
    每个值一个 series（name=组值），data 按 x 轴类别对齐（x 类别取全量
    去重后排序，缺值补 null）——用于"每条产线一条线"这类多系列趋势；
    未传时保持现状（y 多列则每列一条线）。散点/饼图忽略 series_field。
    bar 若分组退化为「系列数≈类目数且每系列仅极少非空点」（BUG-018：
    x=product_id, series=product_name），回退单系列柱图（y 取首值列，
    data 与 xAxis 逐行对齐）。所有 line/bar/pie option 均带 grid 留白。
    """
    ctype = (chart_type or "").strip().lower()
    if ctype not in SUPPORTED_CHART_TYPES or not columns or not rows:
        return None

    if isinstance(y, str):
        y = [y]
    known = set(columns)

    if ctype == "scatter":
        auto_x, auto_y = pick_axes(ctype, columns, rows)
        x = x if x in known else auto_x
        y_list = [c for c in (y or []) if c in known] or auto_y
        if x is None or not y_list:
            return None
        data = [
            [_as_number(row.get(x)), _as_number(row.get(y_list[0]))]
            for row in rows
        ]
        return {
            "title": {"text": f"{x} vs {y_list[0]}", "left": "center"},
            "tooltip": {"trigger": "item"},
            "grid": _chart_grid(with_axis=True),
            "xAxis": {"type": "value", "name": x},
            "yAxis": {"type": "value", "name": y_list[0]},
            "series": [{"name": y_list[0], "type": "scatter", "data": data}],
        }

    numeric = numeric_columns(columns, rows)
    if not numeric:
        return None
    auto_x, auto_y = pick_axes(ctype, columns, rows)
    x = x if x in known else auto_x
    y_list = [c for c in (y or []) if c in known] or auto_y
    if ctype == "pie":
        y_list = y_list[:1]
        if x in numeric and any(c not in numeric for c in columns):
            x = next(c for c in columns if c not in numeric)
    if x is None or not y_list:
        return None

    if ctype == "pie":
        data = [
            {"name": _as_label(row.get(x)), "value": _as_number(row.get(y_list[0]))}
            for row in rows
        ]
        return {
            "title": {"text": " / ".join(y_list), "left": "center"},
            "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
            "legend": {"type": "scroll", "top": 28},
            "grid": _chart_grid(has_legend=True, with_axis=False),
            "series": [{"name": y_list[0], "type": "pie", "radius": "62%", "data": data}],
        }

    # line / bar
    if series_field and series_field in known and series_field != x:
        if not _is_degenerate_bar_grouping(ctype, x, y_list[0], series_field, rows):
            return _grouped_series_option(ctype, x, y_list[0], series_field, rows)
        # BUG-018：bar 稀疏分组回退单系列（y 取首值列，data 与 xAxis 逐行对齐）
    option: dict[str, Any] = {
        "title": {"text": " / ".join(y_list), "left": "center"},
        "tooltip": {"trigger": "axis"},
        "grid": _chart_grid(has_legend=len(y_list) > 1),
        "xAxis": {"type": "category", "name": x, "data": [_as_label(row.get(x)) for row in rows]},
        "yAxis": {"type": "value"},
        "series": [
            {"name": col, "type": ctype, "data": [_as_number(row.get(col)) for row in rows]}
            for col in y_list
        ],
    }
    if len(y_list) > 1:
        option["legend"] = {"data": y_list, "top": 28}
    return option


def _grouped_series_option(
    ctype: str, x: str, y_col: str, series_field: str, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """line/bar 按 series_field 分组的多系列 option。

    x 类别 = 全量行 x 值去重后排序；每个组值一个 series（name=组值，按首次出现
    顺序），data 与 x 类别对齐，缺失处补 None（ECharts 渲染为断点）。
    """
    categories = sorted({_as_label(row.get(x)) for row in rows})
    values: dict[str, dict[str, int | float | None]] = {}
    group_order: list[str] = []
    for row in rows:
        group = _as_label(row.get(series_field))
        if group not in values:
            values[group] = {}
            group_order.append(group)
        values[group][_as_label(row.get(x))] = _as_number(row.get(y_col))
    series = [
        {
            "name": group,
            "type": ctype,
            "data": [values[group].get(category) for category in categories],
        }
        for group in group_order
    ]
    return {
        "title": {"text": y_col, "left": "center"},
        "tooltip": {"trigger": "axis"},
        "legend": {"data": group_order, "top": 28},
        "grid": _chart_grid(has_legend=True),
        "xAxis": {"type": "category", "name": x, "data": categories},
        "yAxis": {"type": "value"},
        "series": series,
    }
