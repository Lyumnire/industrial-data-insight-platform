# AI-assisted
"""A2 编排最小循环（P1 计划 §Task 5 Step 5.3 / docs/03 §3.3 A2、§4 事件协议、§6 异常策略）。

流程：task_started → step(意图理解) → make_plan → plan_ready → [intent=refuse 只读拒绝]
→ step(资源定位) → 检索(ContextPack) → step(生成SQL) → sql_generated → step(安全校验) →
validate_sql → sql_validated → step(执行) → execute_readonly → sql_executing/sql_completed
→ table → [execution_mode=python：step(生成分析代码) → code_generated → step(沙箱执行)
→ 结果表/散点图] → step(生成图表) → chart_building/chart → step(生成结论) → 结论 text_delta
真流式 → done。各阶段前后发射 step_started/step_finished（载荷 {stepId, name, detail}）。
校验/执行失败把报错回喂 LLM 重生成（各 ≤2 次，docs/03 §6 自修复），仍失败发 error 帧；
校验失败属"禁止语句"（写操作）时不进自修复，直接走只读拒绝路径。
python 分支（P2a §Task 11.5）：SQL 取数 → 临时 CSV → LLM 模板优先规划（沙箱约束提示词）
→ A6 沙箱 run_python（Job Object/白名单/超时/临时目录）→ 统计进 insights、散点进
chart(scatter)、聚合表进 table + 标准对象 python_code；代码生成/沙箱失败一律降级为
普通表格分析并在 warnings 注明（docs/03 §6 沙箱降级策略），永不中断 SSE 流。
ml 分支（P2a §Task 12.4）：SQL 取数（行级明细前置要求）→ LLM 结构化推断 MLRequest
→ A7 沙箱训练评估（六算法模板）→ ml_result（camelCase 载荷）+ 异常/预测样本 table +
结果解释 text_delta；失败同样降级不崩流。intent=anomaly 由编排层强制纠正为 ml。
报告模式（P2a §Task 13.1-13.3）：intent=report 或问题含报告/总结/周报/月报 → 主题
固定查询集顺序执行（复用 _sql_chain，每步各发事件）→ insight_generating → report
（markdown+reportId，ADR-3 数字一致性校验内置）→ done 存报告全文。
SQL 链路抽取为 _sql_chain（生成→校验→只读执行→自修复），主流程与报告流程共用；
写操作 SQL（[禁止语句]）经 _ForbiddenSQL 上抛，主流程转只读拒绝路径。
全程异常捕获 → error 事件（code/message 用户可读/suggestion），SSE 流永不裸崩。
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import shutil
import tempfile
import threading
import time
from datetime import date, datetime, time as dtime
from decimal import Decimal
from pathlib import Path
from typing import Any, AsyncIterator

import pandas as pd
import sqlglot
from sqlglot import exp as sqlexp

from app.analytics.tasks import render_template, template_names, template_param_schema
from app.chart.builder import (
    SUPPORTED_CHART_TYPES,
    _date_column,
    build_chart_option,
    numeric_columns,
    pick_axes,
    truncate_title,
)
from app.llm.client import LLMError, LLMNotConfiguredError
from app.llm.prompts import (
    CONCLUSION_SYSTEM_PROMPT,
    ML_PLAN_RETRY_PROMPT,
    ML_PLAN_SYSTEM_PROMPT,
    PY_ANALYSIS_RETRY_PROMPT,
    PY_ANALYSIS_SYSTEM_PROMPT,
    SQL_RETRY_EXEC_TMPL,
    SQL_RETRY_VALIDATE_TMPL,
    SQL_SYSTEM_PROMPT,
)
from app.ml.contracts import MLRequest, MLResponse
from app.ml.modeler import MLDataError, ml_payload, prepare_ml, run_ml
from app.orchestrator.planner import make_plan
from app.report.builder import (
    REPORT_KEYWORDS,
    build_report,
    build_report_full,
    key_findings,
    report_id,
    report_query_set,
)
from app.retriever import ContextPack, CorpusNotLoadedError, Retriever
from app.sandbox.runner import SandboxResult, run_python
from app.schemas.event import SSEEvent
from app.schemas.plan import AnalysisPlan
from app.schemas.result import AnalysisResult, ChartSpec, ExecutionInfo
from app.sqlguard.executor import ExecResult, SQLExecutionError, execute_readonly
from app.sqlguard.validator import SQLValidationError, validate_sql

logger = logging.getLogger("a07.pipeline")


# T-029a / BUG-025：呆滞类问句口径提示 + 臆造 HAVING 空结果纠正
_STAGNANT_RE = re.compile(r"呆滞|滞销|慢动|积压")
_THRESHOLD_IN_Q_RE = re.compile(
    r"低于|高于|大于|小于|不超过|至少|阈值|以上|以下|<|>|≥|≤|安全库存"
)


def _is_stagnant_question(question: str, plan: AnalysisPlan | None) -> bool:
    """是否「库存呆滞」类问句（topic=inventory 或问句含呆滞/滞销/慢动/积压）。"""
    text = question or ""
    if _STAGNANT_RE.search(text):
        return True
    return bool(plan and plan.topic == "inventory" and ("物料" in text or "产品" in text))


def _stagnant_sql_extra() -> str:
    """呆滞口径对齐 corpus 示例的 SQL 附加指令（T-029a）。"""
    return (
        "\n\n【库存呆滞口径】呆滞=高库存+低出库的相对排名，对齐语料示例：\n"
        "SELECT product_id, product_name, ROUND(AVG(inventory_qty), 0) AS avg_stock, "
        "ROUND(AVG(outbound_qty), 1) AS avg_outbound "
        "FROM inventory_records "
        "WHERE record_date >= DATE_SUB((SELECT MAX(record_date) FROM inventory_records), INTERVAL 59 DAY) "
        "GROUP BY product_id, product_name "
        "ORDER BY avg_stock DESC, avg_outbound ASC LIMIT 10;\n"
        "除非用户明确给出阈值，禁止臆造 HAVING（如 avg_outbound < 10 或比例阈值）——"
        "臆造阈值极易得到 0 行。时间窗必须锚 MAX(record_date)，禁止 CURDATE()/NOW()。"
    )


def _sql_has_invented_having(sql: str, question: str) -> bool:
    """SQL 含 HAVING 且用户原话未给阈值 → 疑似臆造过滤（空结果纠正用）。"""
    if not sql or not re.search(r"\bHAVING\b", sql, flags=re.IGNORECASE):
        return False
    return not _THRESHOLD_IN_Q_RE.search(question or "")


def _empty_result_clarify_text(sql: str, question: str) -> str:
    """空结果 clarify 文案：保留 SQL 卡与口径说明，便于诊断（T-029a）。"""
    hints = [
        "时间窗应以数据表 MAX(日期列) 为锚点，避免 CURDATE()/NOW()",
        "「呆滞」类问题应用高库存+低出库的相对排名，而非臆造绝对阈值 HAVING",
        "若确需过滤，请用用户原话中明确给出的阈值",
    ]
    if _sql_has_invented_having(sql, question or ""):
        hints.insert(0, "检测到 SQL 含 HAVING 且用户未给出阈值，阈值可能过严")
    return (
        "未查询到符合条件的数据，可尝试放宽时间范围或更换维度后重新提问。\n"
        f"已执行 SQL：{sql}\n"
        "口径说明：相对时间窗锚定业务表 MAX(日期列)；"
        "库存呆滞=高库存+低出库相对排名（corpus 示例），非绝对阈值过滤。\n"
        "诊断提示：" + "；".join(hints)
    )


def _sql_has_group_by(sql: str) -> bool:
    """AST 判断 SQL 是否含 GROUP BY 聚合（ml 模式硬约束用，2026-09-20 主控修复）。"""
    if not sql or not sql.strip():
        return False
    try:
        stmts = sqlglot.parse(sql, read="mysql")
        return any(
            node.key == "group"
            for stmt in stmts
            if stmt is not None
            for node in stmt.walk()
        )
    except Exception:
        return False  # 解析失败交由 sqlguard 主链路处理，此处不拦截

MAX_REPAIRS = 2        # 校验/执行失败后回喂重生成的总次数上限（docs/03 §6：≤2 次）
TABLE_ROWS_LIMIT = 100  # table 事件与结果对象携带给前端的行数上限
CONCLUSION_ROWS = 40    # 结论 LLM 输入携带的结果行数上限
_CHUNK_MIN, _CHUNK_MAX = 3, 5  # 非流式结论切 3-5 段模拟 text_delta

# 只读拒绝固定文案（规划层 intent=refuse 与 SQL 校验"禁止语句"双层共用）
REFUSAL_TEXT = (
    "本系统为只读分析平台，不支持删除、修改或写入数据。"
    "该平台仅支持查询与统计分析；如需数据维护请联系数据管理员执行。"
)

# 工具注册表 v1（P2 扩展为 tool-call 状态机循环，结构先固定：name → (描述, 处理函数)）


def _tool_search_data_catalog(retriever: Retriever, question: str) -> ContextPack:
    """检索数据目录：召回相关表/指标口径/示例对。"""
    return retriever.retrieve(question)


def _tool_get_table_schema(pack: ContextPack, table_name: str) -> str:
    """取指定表的 M-Schema 文本；未召回返回空串。"""
    for table in pack.tables:
        if table.name == table_name:
            return table.m_schema
    return ""


def _tool_execute_sql(sql: str, cfg: Any) -> ExecResult:
    """只读执行单条已校验 SQL（红线 R1/R9：入参必须先过 validate_sql）。"""
    return execute_readonly(sql, cfg)


def _tool_build_chart(
    chart_type: str, columns: list[str], rows: list[dict[str, Any]],
    x: str | None = None, y: str | list[str] | None = None,
) -> dict[str, Any] | None:
    """后端模板拼 ECharts option（禁止 LLM 生成 option）。"""
    return build_chart_option(chart_type, columns, rows, x=x, y=y)


def _tool_run_python_analysis(
    code: str, input_csv_path: str | None = None, timeout_s: float | None = None
) -> SandboxResult:
    """在 A6 沙箱中执行 pandas 分析代码（import 白名单 + Job Object/timeout + 临时目录隔离）。"""
    return run_python(code, input_csv_path, timeout_s)


def _tool_run_ml_model(req: MLRequest, *, timeout_s: float | None = None) -> MLResponse:
    """A7 建模器：按统一 ML 契约在沙箱内训练评估模型（六算法模板，T-012）。"""
    return run_ml(req, timeout_s=timeout_s)


def _tool_generate_report(
    topic: str | None, question: str, steps: list[dict[str, Any]], llm: Any | None = None
) -> str:
    """A8 报告生成器：汇总多步执行结果生成结构化 Markdown 报告（ADR-3 数字校验内置，T-013）。"""
    return build_report(topic, question, steps, llm)


TOOL_REGISTRY: dict[str, tuple[str, Any]] = {
    "search_data_catalog": ("检索数据目录，召回相关表/指标口径/示例对（P1 关键词版）", _tool_search_data_catalog),
    "get_table_schema": ("获取指定表的 M-Schema 结构（DDL+注释+样例值）", _tool_get_table_schema),
    "execute_sql": ("以只读账号执行单条已通过白名单校验的 SQL", _tool_execute_sql),
    "build_chart": ("按结果集与图表类型用后端模板拼装 ECharts option", _tool_build_chart),
    "run_python_analysis": ("在 A6 沙箱中执行 pandas 分析代码（import 白名单/超时/临时目录隔离）", _tool_run_python_analysis),
    "run_ml_model": ("按统一 ML 契约执行建模（六算法模板，沙箱内训练评估并持久化模型）", _tool_run_ml_model),
    "generate_report": ("汇总多步执行结果生成结构化 Markdown 报告（反幻觉数字一致性校验内置）", _tool_generate_report),
}


class _PipelineError(Exception):
    """带用户可读信息的流程内错误：触发 error 事件（code/message/suggestion）。"""

    def __init__(self, code: str, message: str, suggestion: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.suggestion = suggestion


class _ForbiddenSQL(Exception):
    """SQL 校验发现写操作（[禁止语句]）：主流程转只读拒绝路径，报告流程按步骤失败处理。"""


# SQL 执行错误分类（T-017 / bug-log P2 池：缺表与基础设施错误不应触发无谓 SQL 重生成）
_MISSING_TABLE_MARKERS: tuple[str, ...] = (
    "unknown table",
    "1146",
    "table '",
    "table `",
)
_INFRA_ERROR_MARKERS: tuple[str, ...] = (
    "can't connect",
    "cannot connect",
    "connection refused",
    "connection reset",
    "connection timed out",
    "connection aborted",
    "access denied",
    "too many connections",
    "2002",
    "2003",
    "2006",
    "2013",
    "1045",
)


def _sql_exec_error_kind(exc: Exception) -> str | None:
    """分类 SQL 执行错误：missing_table | infra | None（可回喂 LLM 修复）。

    - missing_table：业务表尚未落库（如库存主题依赖 T-015）——重生成 SQL 无法建表；
    - infra：连接/鉴权等基础设施故障——与 SQL 正确性无关，重试无意义。
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    table_gone = any(m in text for m in _MISSING_TABLE_MARKERS) and (
        "doesn't exist" in text or "does not exist" in text or "unknown table" in text or "1146" in text
    )
    if table_gone or "unknown table" in text or "1146" in text:
        return "missing_table"
    if any(m in text for m in _INFRA_ERROR_MARKERS):
        # 缺表误判防护：ProgrammingError(1146) 已在上分支返回
        if "doesn't exist" in text or "does not exist" in text:
            return "missing_table"
        return "infra"
    return None


# ---- SQL 生成/结论等提示词已集中迁移至 app/llm/prompts.py（P2a §Task 11.5）----


# ---- 内部工具函数 ----


def _emit(event_type: str, **data: Any) -> str:
    return SSEEvent(type=event_type, data=data).to_sse_frame()


def _normalize_cell(value: Any) -> Any:
    """行值归一化：Decimal→float、日期→ISO 字符串、bytes→str，保证 JSON 可序列化。"""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, (date, dtime)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _normalize_rows(columns: list[str], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{col: _normalize_cell(row.get(col)) for col in columns} for row in rows]


def _extract_sql(content: str | None) -> str:
    """从 LLM 输出提取 SQL：剥代码块标记；容忍 {"sql": ...} 形式。"""
    text = (content or "").strip()
    fenced = re.search(r"```(?:sql)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, dict) and isinstance(data.get("sql"), str):
                text = data["sql"].strip()
        except ValueError:
            pass
    return text.strip().rstrip(";")


def _chunk_text(text: str) -> list[str]:
    """非流式结论切 3-5 段模拟 text_delta。"""
    text = (text or "").strip() or "分析完成，结果见上表。"
    parts = [p for p in re.split(r"(?<=[。！？!?；;])\s*|\n+", text) if p and p.strip()]
    if len(parts) < _CHUNK_MIN:
        size = max(1, math.ceil(len(text) / _CHUNK_MIN))
        parts = [text[i : i + size] for i in range(0, len(text), size)]
    elif len(parts) > _CHUNK_MAX:
        step = math.ceil(len(parts) / _CHUNK_MAX)
        parts = ["".join(parts[i : i + step]) for i in range(0, len(parts), step)]
    return parts[:_CHUNK_MAX]


def _split_insights(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"(?<=[。！？!?；;])\s*|\n+", text or "") if p.strip()]
    return parts


def _fmt_cell(value: Any) -> str:
    return "" if value is None else str(_normalize_cell(value))


def _auto_chart_type(columns: list[str], rows: list[dict[str, Any]]) -> str:
    """默认图表：含日期列→line（趋势），否则分组聚合→bar。"""
    if _date_column(columns, rows):
        return "line"
    return "bar"


def _make_chart(
    plan: AnalysisPlan, question: str, columns: list[str], rows: list[dict[str, Any]]
) -> tuple[ChartSpec | None, dict[str, Any] | None]:
    """选定图表类型并拼装 option；无法出图返回 (None, None)。"""
    if not rows or not columns or not numeric_columns(columns, rows):
        return None, None
    chart_type = plan.chart_type if plan.chart_type in SUPPORTED_CHART_TYPES else _auto_chart_type(columns, rows)
    x, y_list = pick_axes(chart_type, columns, rows)
    option = build_chart_option(
        chart_type, columns, rows, x=x, y=y_list, series_field=_pick_series_field(plan, columns, x)
    )
    if option is None:
        return None, None
    option["title"]["text"] = truncate_title(plan.expected_output or question)
    spec = ChartSpec(type=chart_type, x=x, y=y_list, series=option.get("series", []))
    return spec, option


def _pick_series_field(plan: AnalysisPlan, columns: list[str], x: str | None) -> str | None:
    """多系列维度选择：plan.dimensions[0] 存在于结果列且不等于 x 轴列时用作 series_field。

    用于"每条产线一条线"这类多系列折线/柱状；不满足条件返回 None 走原有单系列逻辑。
    bar 若分组退化（系列数≈类目数且每系列稀疏，如 x=product_id / series=product_name），
    由 chart.builder._is_degenerate_bar_grouping 回退单系列（BUG-018 / T-028）——
    本函数无 rows 上下文，稀疏判定不在这里做。
    """
    if not plan.dimensions:
        return None
    dim = plan.dimensions[0]
    if dim in columns and dim != x:
        return dim
    return None


# ---- python 执行模式辅助（P2a §Task 11.5，A6 沙箱接入）----

_PY_META_KEYS = {"summary", "tables", "scatter"}  # insights 数值行中跳过的非统计键

_PY_STAT_LABELS = {
    "pearson": "Pearson 相关系数",
    "spearman": "Spearman 相关系数",
    "n": "有效样本数",
    "point_count": "散点数",
    "group_col": "分组列",
    "value_col": "数值列",
    "agg": "汇总方式",
    "x_col": "X 变量",
    "y_col": "Y 变量",
}


def _strip_json_fence(text: str | None) -> str:
    """剥掉 LLM 可能附带的 ```json 代码块标记。"""
    text = (text or "").strip()
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _parse_analysis_choice(
    content: str | None, columns: list[str]
) -> tuple[str, dict[str, Any], None] | tuple[None, None, str] | None:
    """解析 LLM 的"模板参数 or 自由代码"选择（P2a §Task 11.4/11.5，模板优先）。

    返回 (template_name, params, None) 或 (None, None, free_code)；非法输出返回 None
    （由调用方重试/降级，docs/03 §6）。

    BUG-017 / T-028：按模板参数 schema 区分「列名参数」与「枚举参数」——
    列名参数（group_col/value_col/x_col/y_col…）须逐字存在于结果列清单；
    枚举参数（agg=mean|sum|max|min|count…）走白名单，不再被列名校验误伤。
    未知模板无 schema 时保持保守策略：所有非空字符串值仍须在 columns 中。
    """
    try:
        data = json.loads(_strip_json_fence(content))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    template = data.get("template")
    if isinstance(template, str) and template.strip():
        template = template.strip()
        params = data.get("params")
        params = {str(k): v for k, v in params.items()} if isinstance(params, dict) else {}
        schema = template_param_schema(template)
        if schema is not None:
            column_params: frozenset[str] = schema["column_params"]
            enum_params: dict[str, frozenset[str]] = schema["enum_params"]
            for key, value in params.items():
                if key in column_params:
                    # 列名参数：提示词约束 + 此处复核，防臆造列
                    if isinstance(value, str) and value.strip() and value.strip() not in columns:
                        return None
                elif key in enum_params:
                    # 枚举参数：白名单校验（大小写不敏感；缺省交由 render_template 默认值）
                    if value is not None and str(value).strip():
                        if str(value).strip().lower() not in enum_params[key]:
                            return None
                # 其余参数：模板渲染层会忽略/报错，此处不按列名误伤（BUG-017）
        else:
            # 未知模板：无类型信息，保守复核所有非空字符串值须为结果列
            for key, value in params.items():
                if isinstance(value, str) and value.strip() and value.strip() not in columns:
                    return None
        return template, params, None
    code = data.get("code")
    if isinstance(code, str) and code.strip():
        return None, None, code.strip()
    return None


def _sandbox_table_payload(table: Any) -> tuple[list[str], list[dict[str, Any]]] | None:
    """把沙箱 tables 项（DataFrame 序列化产物或普通 {columns,rows}）转成标准载荷。"""
    if isinstance(table, dict):
        columns = table.get("columns")
        rows = table.get("rows")
        if isinstance(columns, list) and isinstance(rows, list):
            return [str(c) for c in columns], list(rows)[:TABLE_ROWS_LIMIT]
    return None


def _scatter_chart(
    scatter: dict[str, Any], plan: AnalysisPlan, question: str
) -> tuple[ChartSpec | None, dict[str, Any] | None]:
    """沙箱散点数据 → scatter ChartSpec + ECharts option（后端模板拼装，禁 LLM 生成）。"""
    points_raw = scatter.get("points")
    if not isinstance(points_raw, list) or not points_raw:
        return None, None
    x = str(scatter.get("x") or "x")
    y = str(scatter.get("y") or "y")
    points: list[list[float]] = []
    for pair in points_raw:
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            try:
                points.append([float(pair[0]), float(pair[1])])
            except (TypeError, ValueError):
                continue
    if not points:
        return None, None
    option = {
        "title": {"text": truncate_title(plan.expected_output or question), "left": "center"},
        "tooltip": {"trigger": "item"},
        "grid": {"top": 56, "bottom": 52, "left": 56, "right": 32, "containLabel": True},
        "xAxis": {"type": "value", "name": x},
        "yAxis": {"type": "value", "name": y},
        "series": [{"name": y, "type": "scatter", "data": points}],
    }
    spec = ChartSpec(type="scatter", x=x, y=[y], series=option["series"])
    return spec, option


def _stats_insights(stats: dict[str, Any]) -> list[str]:
    """沙箱 stats → insights 文本行（summary 首条 + 数值统计逐条）。"""
    lines: list[str] = []
    summary = stats.get("summary")
    if isinstance(summary, str) and summary.strip():
        lines.append(summary.strip())
    for key, value in stats.items():
        if key in _PY_META_KEYS or isinstance(value, bool):
            continue
        if isinstance(value, float):
            lines.append(f"{_PY_STAT_LABELS.get(key, key)}：{round(value, 4)}")
        elif isinstance(value, int):
            lines.append(f"{_PY_STAT_LABELS.get(key, key)}：{value}")
    return lines


def _python_gen_messages(
    question: str, columns: list[str], rows: list[dict[str, Any]], pack: ContextPack
) -> list[dict[str, str]]:
    """Python 分析代码规划 LLM 输入：问题 + 结果列清单 + 样例行（反臆造列名）。"""
    sample_rows = rows[:10]
    table_lines = [" | ".join(columns)] + [
        " | ".join(_fmt_cell(row.get(col)) for col in columns) for row in sample_rows
    ]
    metric_lines = "\n".join(f"- {m.name}（{m.code}）: {m.formula_sql}" for m in pack.metrics)
    user = (
        f"用户问题：{question}\n\n"
        f"结果列清单（params 列名只能从这里选）：{columns}\n\n"
        f"查询结果预览（共 {len(rows)} 行，展示前 {len(sample_rows)} 行）：\n" + "\n".join(table_lines)
    )
    if metric_lines:
        user += f"\n\n指标口径：\n{metric_lines}"
    return [
        {"role": "system", "content": PY_ANALYSIS_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _python_conclusion_messages(
    question: str, sql: str, stats: dict[str, Any], pack: ContextPack
) -> list[dict[str, str]]:
    """python 模式结论 LLM 输入：沙箱统计结果替代原始表格，反幻觉规则不变。"""
    metric_lines = "\n".join(f"- {m.name}（{m.code}）: {m.formula_sql} —— {m.description}" for m in pack.metrics)
    stat_lines = "\n".join(_stats_insights(stats)) or json.dumps(stats, ensure_ascii=False, default=str)[:1000]
    user = (
        f"用户问题：{question}\n\n"
        f"查询 SQL：\n{sql}\n\n"
        f"指标口径：\n{metric_lines or '（无）'}\n\n"
        f"Python 沙箱分析结果（全部数字必须来自这里）：\n{stat_lines}"
    )
    return [
        {"role": "system", "content": CONCLUSION_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


# ---- ml 执行模式辅助（P2a §Task 12.4，A7 建模器接入）----

_METRIC_LABELS = {
    "mae": "MAE",
    "rmse": "RMSE",
    "r2": "R²",
    "accuracy": "准确率",
    "precision": "精确率",
    "recall": "召回率",
    "f1": "F1",
    "silhouette": "轮廓系数",
    "n_anomalies": "异常记录数",
    "anomaly_ratio": "异常占比",
    "threshold": "异常分数阈值",
}


def _ml_plan_messages(
    question: str, columns: list[str], rows: list[dict[str, Any]], pack: ContextPack
) -> list[dict[str, str]]:
    """ML 方案规划 LLM 输入：问题 + 结果列清单 + 样例行（列名只能从这里选，反臆造）。"""
    sample_rows = rows[:10]
    table_lines = [" | ".join(columns)] + [
        " | ".join(_fmt_cell(row.get(col)) for col in columns) for row in sample_rows
    ]
    user = (
        f"用户问题：{question}\n\n"
        f"结果列清单（features/target 列名只能从这里选）：{columns}\n\n"
        f"查询结果预览（共 {len(rows)} 行，展示前 {len(sample_rows)} 行）：\n" + "\n".join(table_lines)
    )
    metric_lines = "\n".join(f"- {m.name}（{m.code}）: {m.formula_sql}" for m in pack.metrics)
    if metric_lines:
        user += f"\n\n指标口径：\n{metric_lines}"
    return [
        {"role": "system", "content": ML_PLAN_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _parse_ml_plan(content: str | None, columns: list[str], data_ref: str) -> MLRequest | None:
    """解析 LLM 建模方案为 MLRequest（结构校验）；非法返回 None（由调用方重试/降级）。

    列名与数据的匹配交由 prepare_ml 前置校验裁决——那里持有真实数据，能给出
    "缺少列 + 可用列清单"的可读错误（docs/03 §6），此处拦下反而会丢失错误细节。
    """
    try:
        data = json.loads(_strip_json_fence(content))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    model_type = data.get("model_type")
    features = data.get("features")
    if model_type not in ("linear_regression", "decision_tree", "random_forest",
                          "logistic_regression", "kmeans", "isolation_forest"):
        return None
    if not isinstance(features, list) or not features:
        return None
    features = [str(f).strip() for f in features if str(f).strip()]
    if not features:
        return None
    target = data.get("target")
    target = str(target).strip() if isinstance(target, str) and target.strip() else None
    if target is not None and target not in columns:
        return None
    params = data.get("parameters")
    params = {str(k): v for k, v in params.items()} if isinstance(params, dict) else {}
    return MLRequest(
        model_type=model_type, features=features, target=target,
        parameters=params, data_ref=data_ref,
    )


def _ml_conclusion_messages(
    question: str, sql: str, ml_resp: MLResponse
) -> list[dict[str, str]]:
    """ml 模式结论 LLM 输入：MLResponse 指标/重要性/样本替代原始表格，反幻觉规则不变。"""
    sample = json.dumps(ml_resp.predictions_sample[:3], ensure_ascii=False, default=str)[:800]
    imp_text = "、".join(f"{fi.name}={fi.score:.4f}" for fi in ml_resp.feature_importance[:8]) or "（无）"
    user = (
        f"用户问题：{question}\n\n"
        f"查询 SQL：\n{sql}\n\n"
        f"机器学习建模结果（全部数字必须来自这里）：\n"
        f"模型类型：{ml_resp.model_type}（任务类型 {ml_resp.task_type}）\n"
        f"评估指标：{json.dumps(ml_resp.metrics, ensure_ascii=False)}\n"
        f"特征重要性：{imp_text}\n"
        f"样本明细（前 3 行）：{sample}\n"
        f"模型解释：{ml_resp.explanation}"
    )
    return [
        {"role": "system", "content": CONCLUSION_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _ml_insights(ml_resp: MLResponse) -> list[str]:
    """MLResponse → insights 文本（确定性拼装，数字全部来自沙箱评估结果）。"""
    lines: list[str] = []
    if ml_resp.explanation:
        lines.append(ml_resp.explanation)
    for key, value in ml_resp.metrics.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        label = _METRIC_LABELS.get(key, key)
        lines.append(f"{label}：{round(value, 4)}")
    if ml_resp.feature_importance:
        top = "、".join(f"{fi.name}（{fi.score:.4f}）" for fi in ml_resp.feature_importance[:3])
        lines.append(f"特征重要性 TOP3：{top}")
    if ml_resp.model_path:
        lines.append(f"模型已持久化：{ml_resp.model_path}")
    return lines


async def _chat(
    llm: Any, messages: list[dict[str, str]], *, model_tier: str,
    response_format: dict[str, Any] | None = None,
) -> Any:
    """阻塞式 LLM 调用放入线程池，避免卡住事件循环（FakeLLM 同样兼容）。"""
    return await asyncio.to_thread(
        llm.chat, messages, model_tier=model_tier, response_format=response_format
    )


_STREAM_PIECE_DONE = object()  # 流式桥接队列的结束哨兵


async def _chat_stream(llm: Any, messages: list[dict[str, str]], *, model_tier: str) -> AsyncIterator[str]:
    """流式 LLM 调用桥接：阻塞迭代放入工作线程，经线程安全队列转发为异步片段流。

    llm 未提供 chat_stream（如 mock FakeLLM）时立即结束（空流），
    由调用方回退到非流式 chat() + _chunk_text 方案。
    """
    stream_fn = getattr(llm, "chat_stream", None)
    if stream_fn is None:
        return
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Any] = asyncio.Queue()

    def _produce() -> None:
        try:
            for piece in stream_fn(messages, model_tier=model_tier):
                loop.call_soon_threadsafe(queue.put_nowait, piece)
        except BaseException as exc:  # 桥接线程需把任何异常交给消费方裁决
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _STREAM_PIECE_DONE)

    threading.Thread(target=_produce, daemon=True, name="a07-llm-stream").start()
    while True:
        item = await queue.get()
        if item is _STREAM_PIECE_DONE:
            break
        if isinstance(item, BaseException):
            raise item
        yield item


def _refusal_frames(
    question: str, intent: str, tokens_cost: dict[str, int], started: float, step_id: str
) -> list[str]:
    """只读拒绝路径帧序列：step(生成结论) + 1 条 text_delta + done（空结果标准对象）。

    双层触发：规划层 intent=refuse、SQL 校验"禁止语句"失败（防御纵深）。
    execution_info.durationMs=0、dataSource="refused"；不产生任何 SQL/表格事件。
    """
    result = AnalysisResult(
        columns=[],
        rows=[],
        summary={"question": question, "intent": intent, "topic": None, "conclusion": REFUSAL_TEXT},
        insights=[REFUSAL_TEXT],
        warnings=[],
        sql="",
        execution_info=ExecutionInfo(durationMs=0, rowCount=0, dataSource="refused", truncated=False),
    )
    return [
        _emit("step_started", stepId=step_id, name="生成结论", detail="准备只读平台拒绝说明"),
        _emit("step_finished", stepId=step_id, name="生成结论", detail="已拒绝写操作请求"),
        _emit("text_delta", delta=REFUSAL_TEXT, index=0),
        _emit(
            "done",
            **result.model_dump(),
            tokensCost=tokens_cost,
            durationMs=int((time.perf_counter() - started) * 1000),
        ),
    ]


# ---- SQL 链路与报告流程（复用单元，P2a §Task 13.1 抽取）----


async def _sql_chain(
    llm: Any,
    cfg: Any,
    question: str,
    context_text: str,
    out: dict[str, Any],
    *,
    track_usage: Any,
    next_step: Any,
    extra_instruction: str = "",
    emit_steps: bool = True,
) -> AsyncIterator[str]:
    """一次「生成 SQL → 校验 → 只读执行」链路（报错回喂自修复 ≤2 次，docs/03 §6）。

    yields SSE 帧；成功写入 out["exec_result"]/out["final_sql"]；重试耗尽抛
    _PipelineError，写操作 SQL 抛 _ForbiddenSQL（主流程转拒绝路径）。
    emit_steps=False 时不发「生成SQL/安全校验/执行」步骤帧（报告模式外层自有步骤
    事件包裹），sql_generated/sql_validated/sql_executing/sql_completed 始终发送。
    """
    user_content = f"用户问题：{question}\n\n{context_text}"
    if extra_instruction:
        user_content += extra_instruction
    base_messages: list[dict[str, str]] = [
        {"role": "system", "content": SQL_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    messages = base_messages
    repair_count = 0
    while True:
        step_id = next_step()
        if emit_steps:
            yield _emit("step_started", stepId=step_id, name="生成SQL", detail="正在生成查询 SQL")
        resp = await _chat(llm, messages, model_tier="heavy")
        track_usage(resp.usage)
        sql_text = _extract_sql(resp.content)
        yield _emit("sql_generated", sql=sql_text, attempt=repair_count)
        if emit_steps:
            yield _emit("step_finished", stepId=step_id, name="生成SQL", detail=f"第 {repair_count + 1} 次生成完成")

        step_id = next_step()
        if emit_steps:
            yield _emit("step_started", stepId=step_id, name="安全校验", detail="正在校验 SQL 只读白名单")
        try:
            validated_sql = validate_sql(sql_text, dialect="mysql", max_limit=cfg.sql_max_limit)
        except SQLValidationError as exc:
            yield _emit("sql_validated", sql=sql_text, valid=False, message=str(exc))
            if emit_steps:
                yield _emit("step_finished", stepId=step_id, name="安全校验", detail=f"校验未通过：{exc}")
            if str(exc).startswith("[禁止语句]"):
                raise _ForbiddenSQL(str(exc)) from exc
            repair_count += 1
            if repair_count > MAX_REPAIRS:
                raise _PipelineError(
                    "SQL_VALIDATE_FAILED",
                    f"生成的 SQL 连续 {MAX_REPAIRS + 1} 次未通过安全校验，已停止执行",
                    "建议换一种问法（明确表、指标或时间范围）后重试",
                ) from exc
            messages = [
                *base_messages,
                {"role": "assistant", "content": sql_text},
                {"role": "user", "content": SQL_RETRY_VALIDATE_TMPL.format(error=str(exc))},
            ]
            continue

        yield _emit("sql_validated", sql=validated_sql, valid=True, message="安全校验通过（单条只读 SELECT，已补 LIMIT）")
        if emit_steps:
            yield _emit("step_finished", stepId=step_id, name="安全校验", detail="校验通过（单条只读 SELECT，已补 LIMIT）")

        step_id = next_step()
        if emit_steps:
            yield _emit("step_started", stepId=step_id, name="执行", detail="正在只读执行查询")
        yield _emit("sql_executing", sql=validated_sql)
        try:
            exec_result = await asyncio.to_thread(TOOL_REGISTRY["execute_sql"][1], validated_sql, cfg)
        except SQLExecutionError as exc:
            if emit_steps:
                yield _emit("step_finished", stepId=step_id, name="执行", detail=f"执行失败：{exc}")
            kind = _sql_exec_error_kind(exc)
            if kind == "missing_table":
                # 缺表（如库存/工单主题表尚未由数据组落库）：重生成 SQL 无法创建表，
                # 立即以可读错误收口，避免无谓 LLM 重试（T-017 库存主题准备）
                raise _PipelineError(
                    "TABLE_MISSING",
                    f"查询所依赖的数据表在库中不存在，已停止自动重试：{str(exc)[:220]}",
                    "该业务主题的数据表可能尚未初始化（库存/工单主题依赖数据组 T-015 落表）；"
                    "请确认 mes_demo 已建表，或改问已有表覆盖的主题",
                ) from exc
            if kind == "infra":
                raise _PipelineError(
                    "INFRA_ERROR",
                    f"数据库基础设施错误，已停止自动重试（与 SQL 正确性无关）：{str(exc)[:220]}",
                    "请检查 MySQL 服务与只读账号配置是否可用，恢复后重试",
                ) from exc
            repair_count += 1
            if repair_count > MAX_REPAIRS:
                raise _PipelineError(
                    "SQL_EXECUTE_FAILED",
                    "SQL 执行失败，自动修复仍未成功",
                    "建议检查问题中的表/字段/时间条件，或联系管理员查看执行审计日志",
                ) from exc
            messages = [
                *base_messages,
                {"role": "assistant", "content": validated_sql},
                {"role": "user", "content": SQL_RETRY_EXEC_TMPL.format(error=str(exc))},
            ]
            continue

        yield _emit(
            "sql_completed",
            sql=validated_sql,
            elapsedMs=int(exec_result.elapsed_ms),
            rowCount=exec_result.rowcount,
            truncated=exec_result.truncated,
        )
        if emit_steps:
            yield _emit(
                "step_finished",
                stepId=step_id,
                name="执行",
                detail=f"返回 {exec_result.rowcount} 行，耗时 {int(exec_result.elapsed_ms)} ms",
            )
        out["exec_result"] = exec_result
        out["final_sql"] = validated_sql
        return


REPORT_STEP_ROWS = 50  # 单个报告查询步骤进入报告输入/叙述的明细行数上限


async def _report_flow(
    llm: Any,
    retriever: Retriever,
    cfg: Any,
    plan: AnalysisPlan,
    question: str,
    tokens_cost: dict[str, int],
    started: float,
    next_step: Any,
    track_usage: Any,
) -> AsyncIterator[str]:
    """报告流程（P2a §Task 13.1-13.3）：主题固定查询集顺序执行 → 汇总生成反幻觉报告。

    每步复用 _sql_chain（白名单校验/只读执行/自修复）并各发事件；单步失败记录后继续，
    全部失败才抛 _PipelineError。报告全文经 ADR-3 数字一致性校验后随 report 事件下发
    并随 done 存档（summary.report + report/reportId 附加字段）。
    """
    topic = plan.topic
    query_set = report_query_set(topic)
    rid = report_id()
    steps: list[dict[str, Any]] = []
    total_rows = 0
    for spec in query_set:
        qname, qdesc = spec["name"], spec["question"]
        step_id = next_step()
        yield _emit("step_started", stepId=step_id, name=f"报告查询：{qname}", detail=qdesc)
        entry: dict[str, Any] = {
            "name": qname, "description": qdesc, "sql": "", "ok": False,
            "error": None, "columns": [], "rows": [], "stats": {},
        }
        try:
            pack = TOOL_REGISTRY["search_data_catalog"][1](retriever, qdesc)
            context_text = retriever.render_context(pack)
            chain_out: dict[str, Any] = {}
            async for frame in _sql_chain(
                llm, cfg, qdesc, context_text, chain_out,
                track_usage=track_usage, next_step=next_step, emit_steps=False,
            ):
                yield frame
            exec_result = chain_out["exec_result"]
            q_columns = list(exec_result.columns)
            q_rows = _normalize_rows(q_columns, exec_result.rows)
            q_execution_info = ExecutionInfo(
                durationMs=int(exec_result.elapsed_ms),
                rowCount=exec_result.rowcount,
                dataSource=f"{cfg.mysql_db}(MySQL 只读)",
                truncated=exec_result.truncated,
            )
            yield _emit(
                "table",
                columns=q_columns,
                rows=q_rows[:TABLE_ROWS_LIMIT],
                total=exec_result.rowcount,
                execution_info=q_execution_info.model_dump(),
            )
            entry.update(
                ok=True,
                sql=chain_out["final_sql"],
                columns=q_columns,
                rows=q_rows[:REPORT_STEP_ROWS],
                stats={"rowCount": exec_result.rowcount},
            )
            total_rows += exec_result.rowcount
            yield _emit("step_finished", stepId=step_id, name=f"报告查询：{qname}", detail=f"返回 {exec_result.rowcount} 行")
        except (_PipelineError, _ForbiddenSQL, CorpusNotLoadedError) as exc:
            entry["error"] = str(exc)[:200]
            yield _emit("step_finished", stepId=step_id, name=f"报告查询：{qname}", detail=f"查询失败：{entry['error']}")
        steps.append(entry)

    ok_steps = [s for s in steps if s["ok"]]
    if not ok_steps:
        first_err = next((s.get("error") for s in steps if s.get("error")), "")
        if topic == "inventory":
            message = "库存主题报告的数据查询全部失败，无法生成报告"
            hint = (
                "库存相关表 inventory_records / production_orders 可能尚未在 mes_demo 落库"
                "（依赖数据组 T-015）；待数据底座就绪后重试，或改问已有表覆盖的主题"
            )
        else:
            message = "报告所需的数据查询全部失败，无法生成报告"
            hint = "请稍后重试；或先单独验证相关数据查询是否可用"
        if first_err:
            message += f"；最近错误：{first_err[:160]}"
        raise _PipelineError(
            "REPORT_STEPS_FAILED",
            message,
            hint,
        )

    yield _emit("insight_generating", reportId=rid, topic=topic or "general", steps=len(ok_steps))
    step_id = next_step()
    yield _emit("step_started", stepId=step_id, name="生成报告", detail="正在汇总各步执行结果并生成报告（反幻觉数字校验）")
    markdown, report_warnings = await asyncio.to_thread(build_report_full, topic, question, steps, llm)
    yield _emit("report", reportId=rid, markdown=markdown, topic=topic or "general", warnings=report_warnings)
    if report_warnings:
        detail = f"报告已生成（{len(markdown)} 字符），{len(report_warnings)} 条数字校验告警"
    else:
        detail = f"报告已生成（{len(markdown)} 字符），数字一致性校验通过"
    yield _emit("step_finished", stepId=step_id, name="生成报告", detail=detail)

    result = AnalysisResult(
        columns=[],
        rows=[],
        summary={"question": question, "intent": plan.intent, "topic": topic, "reportId": rid, "report": markdown},
        insights=key_findings(ok_steps) or ["报告已生成"],
        warnings=report_warnings,
        sql=None,
        execution_info=ExecutionInfo(
            durationMs=int((time.perf_counter() - started) * 1000),
            rowCount=total_rows,
            dataSource=f"{cfg.mysql_db}(MySQL 只读)",
            truncated=False,
        ),
    )
    yield _emit(
        "done",
        **result.model_dump(),
        report=markdown,
        reportId=rid,
        tokensCost=tokens_cost,
        durationMs=int((time.perf_counter() - started) * 1000),
    )


# ---- 主流程 ----


async def run_analysis(
    req: Any, llm: Any, retriever: Retriever, cfg: Any
) -> AsyncIterator[str]:
    """执行一次分析并逐帧产出 SSE 文本（`event: <type>\\ndata: <json>\\n\\n`）。

    req 鸭子类型：至少具备 question/sessionId/messageId/history 属性
    （即 app.api.routes.AnalyzeRequest）。
    """
    started = time.perf_counter()
    question = str(getattr(req, "question", "") or "").strip()
    session_id = str(getattr(req, "sessionId", "") or "")
    message_id = str(getattr(req, "messageId", "") or "")
    history = list(getattr(req, "history", None) or [])
    tokens_cost = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    step_seq = 0

    def _next_step() -> str:
        nonlocal step_seq
        step_seq += 1
        return str(step_seq)

    def _track_usage(usage: dict[str, int] | None) -> None:
        for key in tokens_cost:
            if usage and isinstance(usage.get(key), int):
                tokens_cost[key] += usage[key]

    try:
        yield _emit("task_started", sessionId=session_id, messageId=message_id, question=question)

        # 1) 规划：意图理解 + 任务规划（失败重试/兜底见 planner）
        step_id = _next_step()
        yield _emit("step_started", stepId=step_id, name="意图理解", detail="正在理解问题意图并规划分析任务")
        plan = await asyncio.to_thread(make_plan, llm, question, history)
        yield _emit(
            "step_finished",
            stepId=step_id,
            name="意图理解",
            detail=f"意图={plan.intent}，主题={plan.topic or '未识别'}，建议图表={plan.chart_type or '自动'}",
        )
        # 1.4) 规划矫正（编排规则，P2a §Task 11 场景 3）：intent=correlation 一律走
        # A6 沙箱 python 执行——相关性分析必须经沙箱产出散点与相关系数；规划器 light
        # 档对"是否需要 Python"判断不稳（真实冒烟曾填 sql），此处编排层强制纠正。
        # 须在 plan_ready 之前执行，保证前端分析档案 Drawer 拿到的是纠正后的 plan。
        if plan.intent == "correlation" and plan.execution_mode == "sql":
            plan.execution_mode = "python"
            if plan.chart_type is None:
                plan.chart_type = "scatter"
            logger.info("plan_corrected intent=correlation mode=sql->python")
        # 1.45) 规划矫正（编排规则，P2a §Task 12.4）：intent=anomaly 一律走 A7 ml 执行——
        # 异常检测必须经沙箱隔离森林产出异常分数与 top 异常样本；与 correlation 同理，
        # light 档规划不稳时由编排层强制纠正（在 plan_ready 之前，保证 Drawer 拿到纠正后 plan）。
        if plan.intent == "anomaly" and plan.execution_mode == "sql":
            plan.execution_mode = "ml"
            logger.info("plan_corrected intent=anomaly mode=sql->ml")
        yield _emit("plan_ready", **plan.model_dump())

        # 1.5) 规划层拒写：intent=refuse → 不检索、不生成 SQL，直接走只读拒绝路径
        if plan.intent == "refuse":
            for frame in _refusal_frames(question, plan.intent, tokens_cost, started, _next_step()):
                yield frame
            return

        # 1.55) 报告模式（P2a §Task 13.1）：intent=report 或问题含报告/总结/周报/月报 →
        #       主题固定查询集顺序执行（每步复用 SQL 链路并各发事件）→ 反幻觉报告生成。
        if plan.intent == "report" or any(k in question for k in REPORT_KEYWORDS):
            async for frame in _report_flow(
                llm, retriever, cfg, plan, question, tokens_cost, started,
                _next_step, _track_usage,
            ):
                yield frame
            return

        # 2) 检索：ContextPack（工具注册表 v1 之 search_data_catalog）
        step_id = _next_step()
        yield _emit("step_started", stepId=step_id, name="资源定位", detail="正在检索相关表结构与指标口径")
        pack = TOOL_REGISTRY["search_data_catalog"][1](retriever, question)
        context_text = retriever.render_context(pack)
        yield _emit(
            "step_finished",
            stepId=step_id,
            name="资源定位",
            detail=f"召回 {len(pack.tables)} 张表、{len(pack.metrics)} 条指标口径",
        )

        # 3) SQL 生成 → 校验 → 执行（自修复循环 ≤2 次；链路抽取复用于报告模式各查询步骤）
        sql_extra = ""
        if plan.execution_mode == "ml":
            # 建模前置要求（T-012 冒烟教训：聚合查询只有个位数行，样本 <30 必然建模失败）：
            # ml 模式的取数必须是行级明细，携带候选特征列与目标列。
            sql_extra = (
                "\n\n【建模前置要求】本次查询结果将用于机器学习建模训练：必须输出行级明细 "
                "SELECT（禁止 GROUP BY 聚合），包含与问题相关的候选特征列与目标列（数值列优先），"
                "时间范围放宽到能取得足够样本（至少 30 行、尽量多），明细行按时间倒序排列。"
            )
        elif _is_stagnant_question(question, plan):
            # T-029a / BUG-025：呆滞口径对齐 corpus，抑制臆造 HAVING 导致空结果
            sql_extra = _stagnant_sql_extra()
        chain_out: dict[str, Any] = {}
        try:
            async for frame in _sql_chain(
                llm, cfg, question, context_text, chain_out,
                track_usage=_track_usage, next_step=_next_step, extra_instruction=sql_extra,
            ):
                yield frame
        except _ForbiddenSQL:
            # 防御纵深：写操作 SQL 不进自修复循环，直接走只读拒绝路径
            for frame in _refusal_frames(question, plan.intent, tokens_cost, started, _next_step()):
                yield frame
            return
        exec_result = chain_out["exec_result"]
        final_sql = chain_out["final_sql"]

        # 3.5) ml 模式 GROUP BY 硬约束（主控修复 2026-09-20）：提示词要求行级明细仍可能被
        # 规划随机性绕过（真实冒烟：异常检测生成按设备聚合查询，聚合行喂模型必降级）——
        # AST 检出 GROUP BY 即带纠正信息重生成一次；仍聚合则放行，由 modeler 前置校验兜底。
        if plan.execution_mode == "ml" and _sql_has_group_by(final_sql):
            logger.info("ml_sql_groupby_detected, regenerating row-level SQL")
            yield _emit("step_started", stepId=_next_step(), name="生成SQL",
                        detail="建模需要行级明细：检测到聚合查询，纠正重生成中")
            retry_out: dict[str, Any] = {}
            corrective = (
                (sql_extra or "")
                + "\n\n【纠正】上一次查询使用了 GROUP BY 聚合，机器学习训练必须基于行级明细，"
                "上一次的 SQL 是：\n" + final_sql
                + "\n请完全去掉 GROUP BY 与聚合函数，逐行输出原始明细记录"
                "（每行一台设备/一个批次/一次检验/一次停机事件），保留时间列。"
            )
            try:
                async for frame in _sql_chain(
                    llm, cfg, question, context_text, retry_out,
                    track_usage=_track_usage, next_step=_next_step,
                    extra_instruction=corrective,
                ):
                    yield frame
                if isinstance(retry_out.get("final_sql"), str) and retry_out.get("exec_result"):
                    final_sql = retry_out["final_sql"]
                    exec_result = retry_out["exec_result"]
                    columns = list(exec_result.columns)
                    rows = _normalize_rows(columns, exec_result.rows)
                    execution_info = ExecutionInfo(
                        durationMs=int(exec_result.elapsed_ms),
                        rowCount=exec_result.rowcount,
                        dataSource=f"{cfg.mysql_db}(MySQL 只读)",
                        truncated=exec_result.truncated,
                    )
            except _ForbiddenSQL:
                pass  # 纠正轮出现写操作 SQL：放弃纠正，交由 modeler 前置校验兜底
            if _sql_has_group_by(final_sql):
                logger.warning("ml_sql_still_grouped_after_retry, fallback to modeler precheck")
        # 3.9) 空结果 + 臆造 HAVING → 一次口径纠正重生成（T-029a / BUG-025）
        # LLM 偶发为「呆滞」类问题编造绝对/比例阈值（如 avg_outbound < 10），在合成数据上
        # 极易滤成 0 行；corpus 口径是相对排名、不设臆造阈值。纠正一次后仍空则走 clarify。
        if (exec_result.rowcount == 0 or not exec_result.rows) and _sql_has_invented_having(
            final_sql, question
        ):
            logger.info("empty_result_invented_having_detected, regenerating ranking SQL")
            yield _emit(
                "step_started", stepId=_next_step(), name="生成SQL",
                detail="空结果诊断：检测到臆造 HAVING 阈值，按相对排名口径纠正重生成",
            )
            corrective = (
                (sql_extra or "")
                + "\n\n【纠正】上一次 SQL 执行结果为 0 行，且含用户未要求的 HAVING 阈值：\n"
                + final_sql
                + "\n请按语料示例的相对排名口径重写：去掉臆造的 HAVING/绝对阈值，"
                "输出高库存+低出库对照列（avg_stock / avg_outbound），"
                "ORDER BY avg_stock DESC, avg_outbound ASC；"
                "时间窗锚 MAX(record_date)，禁止 CURDATE()。只输出 SQL 本身。"
            )
            retry_out: dict[str, Any] = {}
            try:
                async for frame in _sql_chain(
                    llm, cfg, question, context_text, retry_out,
                    track_usage=_track_usage, next_step=_next_step,
                    extra_instruction=corrective,
                ):
                    yield frame
                if isinstance(retry_out.get("final_sql"), str) and retry_out.get("exec_result"):
                    final_sql = retry_out["final_sql"]
                    exec_result = retry_out["exec_result"]
            except _ForbiddenSQL:
                pass

        columns = list(exec_result.columns)
        rows = _normalize_rows(columns, exec_result.rows)
        execution_info = ExecutionInfo(
            durationMs=int(exec_result.elapsed_ms),
            rowCount=exec_result.rowcount,
            dataSource=f"{cfg.mysql_db}(MySQL 只读)",
            truncated=exec_result.truncated,
        )

        # 4) 空结果 → clarify（docs/03 §6：引导放宽条件；T-029a 保留 SQL 卡与口径说明）
        if exec_result.rowcount == 0 or not rows:
            yield _emit(
                "table", columns=columns, rows=[], total=0, execution_info=execution_info.model_dump()
            )
            yield _emit(
                "clarify",
                question=_empty_result_clarify_text(final_sql, question),
                options=["扩大时间范围再查一次", "更换分组维度（如按产线/工序/产品）", "换一种问法描述你要的分析"],
                sql=final_sql,
                diagnosis={
                    "rowCount": exec_result.rowcount,
                    "sql": final_sql,
                    "likelyCause": (
                        "HAVING 阈值过严（用户未给出阈值）"
                        if _sql_has_invented_having(final_sql, question)
                        else "时间窗/过滤条件可能过严，或该条件下确实无数据"
                    ),
                    "hints": [
                        "时间窗锚 MAX(日期列) 而非 CURDATE()/NOW()",
                        "呆滞类问题用高库存+低出库相对排名，勿臆造绝对阈值",
                        "HAVING 仅在用户原话或指标口径明确给出阈值时使用",
                    ],
                },
            )
            result = AnalysisResult(
                columns=columns,
                rows=[],
                summary={
                    "question": question,
                    "intent": plan.intent,
                    "topic": plan.topic,
                    "conclusion": "未查询到数据",
                    "sql": final_sql,
                    "diagnosis": (
                        "SQL 含用户未要求的 HAVING 阈值，疑似过严"
                        if _sql_has_invented_having(final_sql, question)
                        else "请检查时间窗与过滤条件"
                    ),
                },
                insights=[_empty_result_clarify_text(final_sql, question)],
                warnings=["未查询到符合条件的数据"],
                sql=final_sql,
                execution_info=execution_info,
            )
            yield _emit(
                "done",
                **result.model_dump(),
                tokensCost=tokens_cost,
                durationMs=int((time.perf_counter() - started) * 1000),
            )
            return

        # 5) table 事件（rows 截前 100，total/truncated 放 execution_info）
        yield _emit(
            "table",
            columns=columns,
            rows=rows[:TABLE_ROWS_LIMIT],
            total=exec_result.rowcount,
            execution_info=execution_info.model_dump(),
        )

        # 5.5) python 分支（P2a §Task 11.5）：SQL 取数 → 临时 CSV → LLM 模板优先规划
        #      → A6 沙箱执行。任何失败（规划/执行/超时）都降级为普通表格分析并记 warnings，
        #      不中断事件流（docs/03 §6 沙箱降级策略）。
        python_code: str | None = None
        sandbox: SandboxResult | None = None
        py_ok = False
        py_stats: dict[str, Any] = {}
        py_columns, py_rows = columns, rows
        py_warnings: list[str] = []
        # ml 分支状态（P2a §Task 12.4，分支见 5.6）
        ml_resp: MLResponse | None = None
        ml_code: str | None = None
        ml_ok = False
        ml_warnings: list[str] = []

        if plan.execution_mode == "python":
            csv_dir = Path(tempfile.mkdtemp(prefix="a07_pyin_"))
            try:
                step_id = _next_step()
                yield _emit("step_started", stepId=step_id, name="生成分析代码", detail="正在规划沙箱分析代码（模板优先）")
                csv_path = csv_dir / "input.csv"
                pd.DataFrame(rows, columns=columns).to_csv(csv_path, index=False, encoding="utf-8")
                gen_messages = _python_gen_messages(question, columns, rows, pack)
                choice: tuple[str, dict[str, Any], None] | tuple[None, None, str] | None = None
                for _attempt in (1, 2):
                    gen_resp = await _chat(
                        llm, gen_messages, model_tier="heavy", response_format={"type": "json_object"}
                    )
                    _track_usage(gen_resp.usage)
                    choice = _parse_analysis_choice(gen_resp.content, columns)
                    if choice is not None:
                        break
                    gen_messages = [
                        *gen_messages,
                        {"role": "assistant", "content": (gen_resp.content or "")[:1000]},
                        {"role": "user", "content": PY_ANALYSIS_RETRY_PROMPT},
                    ]

                if choice is None:
                    py_warnings.append("Python 分析代码生成失败，已降级为普通表格分析")
                    yield _emit("step_finished", stepId=step_id, name="生成分析代码", detail="分析代码规划失败，已降级为普通表格分析")
                else:
                    template_name, params, free_code = choice
                    try:
                        py_code = (
                            render_template(template_name, params)  # type: ignore[arg-type]
                            if template_name is not None
                            else free_code
                        )
                        code_desc = f"模板 {template_name}" if template_name else "自由代码"
                    except ValueError as exc:  # 模板名/参数非法
                        py_code = None
                        code_desc = str(exc)
                    if py_code is None:
                        py_warnings.append(f"Python 分析代码生成失败，已降级为普通表格分析：{code_desc}")
                        yield _emit("step_finished", stepId=step_id, name="生成分析代码", detail=f"生成失败：{code_desc}")
                    else:
                        python_code = py_code
                        yield _emit("code_generated", language="python", code=py_code, source=code_desc)
                        yield _emit("step_finished", stepId=step_id, name="生成分析代码", detail=f"已生成（{code_desc}）")

                        step_id = _next_step()
                        yield _emit("step_started", stepId=step_id, name="沙箱执行", detail="正在隔离环境中执行 Python 分析代码")
                        sandbox = await asyncio.to_thread(
                            TOOL_REGISTRY["run_python_analysis"][1],
                            py_code,
                            str(csv_path),
                            cfg.sandbox_timeout_seconds,
                        )
                        if sandbox.ok and not sandbox.stats.get("error"):
                            py_ok = True
                            py_stats = sandbox.stats
                            yield _emit("step_finished", stepId=step_id, name="沙箱执行", detail=f"执行成功，耗时 {int(sandbox.duration_ms)} ms")
                        else:
                            reason = str(sandbox.error or sandbox.stats.get("error") or "未知原因")
                            py_warnings.append(f"Python 分析执行失败，已降级为普通表格分析：{reason[:120]}")
                            yield _emit("step_finished", stepId=step_id, name="沙箱执行", detail=f"执行失败：{reason[:120]}")
            finally:
                shutil.rmtree(csv_dir, ignore_errors=True)

            py_warnings.extend(sandbox.warnings if sandbox is not None else [])
            # 沙箱聚合表（如 group_summary）作为最终结果表再发一次 table 事件
            if py_ok and sandbox is not None and sandbox.tables:
                table_payload = _sandbox_table_payload(sandbox.tables[0])
                if table_payload is not None:
                    py_columns, py_rows = table_payload
                    yield _emit(
                        "table",
                        columns=py_columns,
                        rows=py_rows,
                        total=len(py_rows),
                        execution_info=execution_info.model_dump(),
                    )

        # 5.6) ml 分支（P2a §Task 12.4）：SQL 取数 → LLM 结构化推断 MLRequest（六算法契约）
        #      → 沙箱训练评估 → ml_result（camelCase 载荷）+ 异常/预测样本 table。
        #      方案推断/前置校验/训练失败一律降级为普通表格分析并记 warnings，不中断事件流。
        if plan.execution_mode == "ml":
            csv_dir_ml = Path(tempfile.mkdtemp(prefix="a07_mlin_"))
            prepared = None
            try:
                csv_path_ml = csv_dir_ml / "input.csv"
                pd.DataFrame(rows, columns=columns).to_csv(csv_path_ml, index=False, encoding="utf-8")

                step_id = _next_step()
                yield _emit("step_started", stepId=step_id, name="生成分析方案", detail="正在从问题推断建模方案（算法/特征/目标）")
                messages_ml = _ml_plan_messages(question, columns, rows, pack)
                ml_req: MLRequest | None = None
                for _attempt in (1, 2):
                    gen_resp = await _chat(
                        llm, messages_ml, model_tier="heavy", response_format={"type": "json_object"}
                    )
                    _track_usage(gen_resp.usage)
                    ml_req = _parse_ml_plan(gen_resp.content, columns, str(csv_path_ml))
                    if ml_req is not None:
                        break
                    messages_ml = [
                        *messages_ml,
                        {"role": "assistant", "content": (gen_resp.content or "")[:1000]},
                        {"role": "user", "content": ML_PLAN_RETRY_PROMPT},
                    ]

                if ml_req is None:
                    ml_warnings.append("ML 建模方案推断失败，已降级为普通表格分析")
                    yield _emit("step_finished", stepId=step_id, name="生成分析方案", detail="建模方案推断失败，已降级为普通表格分析")
                else:
                    # 数据前置校验 + 模板渲染（prepare_ml 持有真实数据，错误可读）
                    try:
                        prepared = await asyncio.to_thread(prepare_ml, ml_req, cfg)
                    except MLDataError as exc:
                        ml_warnings.append(f"ML 建模前置校验失败：{exc}")
                        yield _emit("step_finished", stepId=step_id, name="生成分析方案", detail=f"前置校验失败：{str(exc)[:120]}")
                    if prepared is not None:
                        ml_code = prepared.code
                        yield _emit("code_generated", language="python", code=ml_code, source=f"ML 模板 {ml_req.model_type}")
                        yield _emit(
                            "step_finished",
                            stepId=step_id,
                            name="生成分析方案",
                            detail=f"已确定建模方案：{ml_req.model_type}（任务类型 {prepared.task_type}）",
                        )

                        step_id = _next_step()
                        yield _emit("step_started", stepId=step_id, name="训练评估", detail=f"正在沙箱内训练 {ml_req.model_type} 模型并评估")
                        try:
                            ml_resp = await asyncio.to_thread(run_ml, ml_req, cfg=cfg, prepared=prepared)
                        except MLDataError as exc:
                            ml_warnings.append(f"ML 建模执行失败：{exc}")
                            yield _emit("step_finished", stepId=step_id, name="训练评估", detail=f"训练评估失败：{str(exc)[:120]}")
                        else:
                            ml_ok = True
                            ml_warnings.extend(ml_resp.warnings)
                            yield _emit("ml_result", **ml_payload(ml_resp))
                            # 异常检测/预测样本表（top 异常设备、预测对比等）
                            if ml_resp.predictions_sample:
                                sample_columns = [str(k) for k in ml_resp.predictions_sample[0].keys()]
                                yield _emit(
                                    "table",
                                    columns=sample_columns,
                                    rows=ml_resp.predictions_sample[:TABLE_ROWS_LIMIT],
                                    total=len(ml_resp.predictions_sample),
                                    execution_info=execution_info.model_dump(),
                                )
                            yield _emit(
                                "step_finished",
                                stepId=step_id,
                                name="训练评估",
                                detail=f"训练评估完成（{ml_req.model_type}），模型已持久化",
                            )
            finally:
                shutil.rmtree(csv_dir_ml, ignore_errors=True)
                if prepared is not None:
                    shutil.rmtree(prepared.csv_dir, ignore_errors=True)

        # 6) 图表：ml 成功时图表数据随 ml_result.plots 下发（跳过通用图表）；python 成功
        #    且带散点数据 → scatter；否则由结果表后端模板拼装（禁 LLM 生成）
        spec: ChartSpec | None = None
        option: dict[str, Any] | None = None
        if ml_ok:
            logger.info("chart_skipped reason=ml_mode_plots_in_ml_result model=%s", ml_resp.model_type if ml_resp else "")
        else:
            step_id = _next_step()
            yield _emit("step_started", stepId=step_id, name="生成图表", detail="正在拼装图表配置")
            spec: ChartSpec | None = None
            option: dict[str, Any] | None = None
            scatter_data = sandbox.result.get("scatter") if (py_ok and sandbox is not None) else None
            if isinstance(scatter_data, dict):
                spec, option = _scatter_chart(scatter_data, plan, question)
            if spec is None or option is None:
                spec, option = _make_chart(plan, question, py_columns, py_rows)
            if spec is not None and option is not None:
                yield _emit("chart_building", type=spec.type)
                yield _emit("chart", type=spec.type, x=spec.x, y=spec.y, series=spec.series, option=option)
                yield _emit("step_finished", stepId=step_id, name="生成图表", detail=f"已生成 {spec.type} 图表")
            else:
                logger.info("chart_skipped reason=no_numeric_or_unsupported plan_chart=%s", plan.chart_type)
                yield _emit("step_finished", stepId=step_id, name="生成图表", detail="结果不适合绘图，已跳过图表")

        # 7) 结论：真流式 text_delta（逐片段）；片段流为空回退非流式切块。
        #    python 成功时输入为沙箱统计结果、ml 成功时输入为建模指标（反幻觉：数字只准来自执行结果）。
        step_id = _next_step()
        conclude_step_name = "结果解释" if ml_ok else "生成结论"
        yield _emit(
            "step_started",
            stepId=step_id,
            name=conclude_step_name,
            detail="正在基于执行结果生成结论" if not ml_ok else "正在基于建模结果生成解释",
        )
        if py_ok:
            conclusion_messages = _python_conclusion_messages(question, final_sql, py_stats, pack)
        elif ml_ok:
            conclusion_messages = _ml_conclusion_messages(question, final_sql, ml_resp)
        else:
            conclusion_messages = _conclusion_messages(question, final_sql, pack, py_columns, py_rows)
        try:
            pieces: list[str] = []
            async for piece in _chat_stream(llm, conclusion_messages, model_tier="heavy"):
                pieces.append(piece)
                yield _emit("text_delta", delta=piece, index=len(pieces) - 1)
            if pieces:
                conclusion = "".join(pieces)
            else:
                conclusion_resp = await _chat(llm, conclusion_messages, model_tier="heavy")
                _track_usage(conclusion_resp.usage)
                conclusion = (conclusion_resp.content or "").strip() or "分析完成，结果见上表。"
                for index, chunk in enumerate(_chunk_text(conclusion)):
                    yield _emit("text_delta", delta=chunk, index=index)
        except Exception:
            yield _emit("step_finished", stepId=step_id, name=conclude_step_name, detail="结论生成失败：模型服务异常")
            raise
        yield _emit("step_finished", stepId=step_id, name=conclude_step_name, detail="结论生成完成")

        # 8) done：标准分析结果对象（+ tokensCost/durationMs 附加元信息）
        warnings: list[str] = []
        if exec_result.truncated:
            warnings.append(
                f"结果共 {exec_result.rowcount} 行，已达上限 {cfg.sql_max_limit} 行被截断；"
                "建议增加筛选条件缩小范围"
            )
        elif exec_result.rowcount > TABLE_ROWS_LIMIT:
            warnings.append(f"结果共 {exec_result.rowcount} 行，仅展示前 {TABLE_ROWS_LIMIT} 行")
        if spec is None and not ml_ok:
            warnings.append("当前结果不适合绘图，已省略图表")
        warnings.extend(py_warnings)
        warnings.extend(ml_warnings)

        result = AnalysisResult(
            columns=py_columns,
            rows=py_rows[:TABLE_ROWS_LIMIT],
            summary={"question": question, "intent": plan.intent, "topic": plan.topic, "conclusion": conclusion},
            chart=spec,
            insights=_ml_insights(ml_resp) if ml_ok else (_stats_insights(py_stats) if py_ok else _split_insights(conclusion)),
            warnings=warnings,
            sql=final_sql,
            python_code=python_code or ml_code,
            execution_info=execution_info,
        )
        yield _emit(
            "done",
            **result.model_dump(),
            tokensCost=tokens_cost,
            durationMs=int((time.perf_counter() - started) * 1000),
        )

    except LLMNotConfiguredError as exc:
        logger.warning("pipeline_no_llm_key sessionId=%s", session_id)
        yield _emit(
            "error",
            code="LLM_NOT_CONFIGURED",
            message=str(exc),
            suggestion="请在 .env 中配置 LLM_PRIMARY_API_KEY 后重启引擎，再重新发起分析",
        )
    except LLMError as exc:
        logger.warning("pipeline_llm_failed sessionId=%s error=%s", session_id, exc)
        yield _emit(
            "error",
            code="LLM_ERROR",
            message="AI 模型服务暂时不可用，请稍后重试",
            suggestion="请稍后重新发起分析；若持续失败请联系管理员检查模型服务配置",
        )
    except CorpusNotLoadedError as exc:
        logger.error("pipeline_corpus_missing sessionId=%s error=%s", session_id, exc)
        yield _emit(
            "error",
            code="CORPUS_NOT_LOADED",
            message="数据目录未加载，无法定位业务表",
            suggestion="请确认 a07-data/corpus/corpus.json 存在后调用 /internal/reindex 重新加载",
        )
    except _PipelineError as exc:
        logger.warning("pipeline_error code=%s sessionId=%s message=%s", exc.code, session_id, exc.message)
        yield _emit("error", code=exc.code, message=exc.message, suggestion=exc.suggestion)
    except Exception as exc:  # 兜底：任何漏网异常都以 error 帧收尾（红线 R8）
        logger.exception("pipeline_unhandled sessionId=%s error=%s", session_id, exc)
        yield _emit(
            "error",
            code="INTERNAL_ERROR",
            message="服务内部错误，请稍后重试或联系管理员",
            suggestion="请重新发起分析；若持续失败请联系管理员查看引擎日志",
        )


def _conclusion_messages(
    question: str, sql: str, pack: ContextPack, columns: list[str], rows: list[dict[str, Any]]
) -> list[dict[str, str]]:
    """结论 LLM 输入：SQL + 结果（≤40 行）+ 指标口径，附反幻觉硬规则。"""
    shown = rows[:CONCLUSION_ROWS]
    table_lines = [" | ".join(columns)] + [
        " | ".join(_fmt_cell(row.get(col)) for col in columns) for row in shown
    ]
    metric_lines = "\n".join(f"- {m.name}（{m.code}）: {m.formula_sql} —— {m.description}" for m in pack.metrics)
    user = (
        f"用户问题：{question}\n\n"
        f"查询 SQL：\n{sql}\n\n"
        f"指标口径：\n{metric_lines or '（无）'}\n\n"
        f"查询结果（共 {len(rows)} 行，展示前 {len(shown)} 行）：\n" + "\n".join(table_lines)
    )
    return [
        {"role": "system", "content": CONCLUSION_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
