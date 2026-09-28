# AI-assisted
"""A6 内置分析任务模板（P2a 计划 §Task 11.4）。

模板代码在沙箱内执行（app/sandbox/runner.py）：运行环境已预置
`df`（pandas.DataFrame，来自查询结果 CSV）与 `result`（dict，结果容器）。

协议约定（runner 与 pipeline 共同遵守）：
- `result["tables"]`：list，每项为 DataFrame → 序列化为 {columns, rows≤100}，进标准对象表格；
- `result["scatter"]`：{"x","y","points":[[x,y],...]} → 进 chart 事件（scatter）；
- `result["summary"]`：一句话中文结论 → insights 首条；
- 其余键 → 统计值（stats），由 pipeline 格式化为 insights；
- `result["error"]`：业务层失败说明（样本不足等），执行本身仍算成功，pipeline 据此降级。

LLM 生成的自由代码与模板二选一，模板优先（提示词引导 LLM 优先填模板参数，
降低自由代码风险）。
"""
from __future__ import annotations

from typing import Any

TEMPLATES: dict[str, str] = {
    "correlation": "两列数值的相关性分析（Pearson/Spearman 相关系数 + 散点数据）",
    "group_summary": "按某列分组对数值列汇总（mean/sum/max/min/count + 聚合表）",
}

_ALLOWED_AGGS = ("mean", "sum", "max", "min", "count")
_SCATTER_MAX_POINTS = 500

# 模板参数类型 schema（BUG-017 / T-028）：列名参数 vs 枚举参数分离注册，
# 供 pipeline._parse_analysis_choice 做差异化校验——列名参数复核结果列清单，
# 枚举参数走白名单（防臆造列误伤合法枚举值）。
TEMPLATE_PARAM_SCHEMAS: dict[str, dict[str, Any]] = {
    "correlation": {
        "column_params": frozenset({"x_col", "y_col"}),
        "enum_params": {},
    },
    "group_summary": {
        "column_params": frozenset({"group_col", "value_col"}),
        "enum_params": {"agg": frozenset(_ALLOWED_AGGS)},
    },
}


def template_param_schema(name: str) -> dict[str, Any] | None:
    """取模板参数类型 schema；未知模板返回 None（调用方走保守策略）。"""
    return TEMPLATE_PARAM_SCHEMAS.get(name)

# 模板为 str.format 填参的代码片段；列名等参数一律经 !r 注入为字符串字面量。
# 相关系数用 numpy 手工实现（pearson=np.corrcoef；spearman=秩的 pearson），
# 不用 DataFrame.corr——其在 pandas 2.x 下会尝试 import scipy（沙箱白名单外）。
_CORRELATION_CODE = '''# AI-assisted: 沙箱内执行——相关性分析模板（correlation）
_x_col = {x_col!r}
_y_col = {y_col!r}
_x = pd.to_numeric(df[_x_col], errors="coerce")
_y = pd.to_numeric(df[_y_col], errors="coerce")
_pair = pd.concat([_x.rename(_x_col), _y.rename(_y_col)], axis=1).dropna()
_n = int(len(_pair))
result["x_col"] = _x_col
result["y_col"] = _y_col
if _n < 3:
    result["error"] = "可用于相关性计算的有效样本不足（%d 行 < 3），请放宽条件或更换数值列" % _n
else:
    _xs = _pair[_x_col].astype(float)
    _ys = _pair[_y_col].astype(float)
    if float(_xs.std()) == 0 or float(_ys.std()) == 0:
        result["error"] = "存在取值恒定不变的列，相关系数无定义；请更换数值列"
    else:
        result["n"] = _n
        result["pearson"] = float(np.corrcoef(_xs, _ys)[0, 1])
        result["spearman"] = float(np.corrcoef(_xs.rank(), _ys.rank())[0, 1])
        _points = _pair.head({_max_points})
        result["scatter"] = {{
            "x": _x_col,
            "y": _y_col,
            "points": [[float(a), float(b)] for a, b in zip(_points[_x_col], _points[_y_col])],
            "point_count": _n,
        }}
        result["summary"] = (
            "%s 与 %s 的 Pearson 相关系数为 %.4f，Spearman 相关系数为 %.4f（有效样本 %d 行）"
            % (_x_col, _y_col, result["pearson"], result["spearman"], _n)
        )
'''

_GROUP_SUMMARY_CODE = '''# AI-assisted: 沙箱内执行——分组汇总模板（group_summary）
_group_col = {group_col!r}
_value_col = {value_col!r}
_agg = {agg!r}
_work = df[[_group_col]].copy()
_work["__value__"] = pd.to_numeric(df[_value_col], errors="coerce")
_work = _work.dropna(subset=["__value__"])
result["group_col"] = _group_col
result["value_col"] = _value_col
result["agg"] = _agg
if _work.empty:
    result["error"] = "分组汇总失败：数值列 %s 无有效数值，请更换列或放宽条件" % _value_col
else:
    _stat = _work.groupby(_work[_group_col].astype(str), dropna=False)["__value__"].agg(_agg)
    _table = _stat.reset_index()
    _table.columns = [_group_col, "%s_%s" % (_agg, _value_col)]
    _table = _table.sort_values(_table.columns[1], ascending=False).head(100)
    _table[_group_col] = _table[_group_col].astype(str)
    result["tables"] = [_table]
    _best, _worst = _table.iloc[0], _table.iloc[-1]
    result["summary"] = (
        "按 %s 分组对 %s 做 %s 汇总，共 %d 组；最高的 %s 为 %.4f，最低的 %s 为 %.4f"
        % (_group_col, _value_col, _agg, len(_table),
           _best.iloc[0], float(_best.iloc[1]), _worst.iloc[0], float(_worst.iloc[1]))
    )
'''


def template_names() -> tuple[str, ...]:
    """可用模板名（供提示词与校验）。"""
    return tuple(TEMPLATES)


def template_catalog() -> str:
    """模板目录文本（供系统提示词拼接）。"""
    return "\n".join(f"- {name}：{desc}" for name, desc in TEMPLATES.items())


def _require_str(params: dict[str, Any], key: str, template: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"模板 {template} 缺少必填参数 {key}（须为结果集中存在的列名）")
    return value.strip()


def render_template(name: str, params: dict[str, Any]) -> str:
    """按模板名与参数渲染沙箱代码；模板未知/参数缺失/取值非法时抛 ValueError。"""
    params = params if isinstance(params, dict) else {}
    if name == "correlation":
        x_col = _require_str(params, "x_col", name)
        y_col = _require_str(params, "y_col", name)
        return _CORRELATION_CODE.format(x_col=x_col, y_col=y_col, _max_points=_SCATTER_MAX_POINTS)
    if name == "group_summary":
        group_col = _require_str(params, "group_col", name)
        value_col = _require_str(params, "value_col", name)
        agg = str(params.get("agg") or "mean").strip().lower()
        if agg not in _ALLOWED_AGGS:
            raise ValueError(
                f"模板 group_summary 的 agg 取值非法：{agg!r}（允许 {'/'.join(_ALLOWED_AGGS)}）"
            )
        return _GROUP_SUMMARY_CODE.format(group_col=group_col, value_col=value_col, agg=agg)
    raise ValueError(f"未知分析模板：{name!r}（可用：{', '.join(TEMPLATES)}）")
