# AI-assisted
"""A8 反幻觉报告生成器（P2a 计划 §Task 13.1-13.2 / docs/03 §3.3 A8、§4 report 事件）。

build_report(topic, question, steps) -> Markdown：
- 结构（docs/03 §3.3 A8）：报告主题/分析问题/数据来源/时间范围/关键指标/图表锚点/
  核心发现/异常发现/结论建议/生成时间 十个小节；
- 反幻觉硬规则（ADR-3 / 红线 R5）：LLM 只做叙述，输入=各步执行结果 JSON；
  确定性小节（主题/来源/时间/指标/锚点）由代码拼装，数字全部来自 steps；
- 数字一致性校验：生成后提取报告中所有数值，逐一溯源到 steps 的 rows/stats
  （容差 0.5%，另放行两两差值与比值×100 这类合法比较、豁免日期/时间表述与个位结构数），
  失败重生成 ≤1 次，仍失败剔除违规句并记 warnings；
- llm=None 时叙述小节由步骤数据确定性拼装（无 LLM 环境兜底，数字天然可溯源）。

TOPIC_QUERY_SETS：报告模式的主题固定查询集（质量/生产/设备/库存），
general/None 走通用兜底集；每步由编排层复用现有 SQL 链路执行。
"""
from __future__ import annotations

import json
import logging
import re
from bisect import bisect_left
from datetime import date, datetime, timedelta
from typing import Any

from app.llm.prompts import REPORT_SYSTEM_PROMPT

logger = logging.getLogger("a07.report")

# 报告模式关键词触发（计划 §Task 13.1：intent=report 或问题含下列词）
REPORT_KEYWORDS: tuple[str, ...] = ("报告", "总结", "周报", "月报")

TOPIC_NAMES: dict[str, str] = {
    "production": "生产分析",
    "quality": "质量分析",
    "equipment": "设备分析",
    "inventory": "库存分析",
    "general": "综合分析",
}

# 主题固定查询集（§Task 13.1）；每项由编排层复用 SQL 链路执行并各发事件
TOPIC_QUERY_SETS: dict[str, list[dict[str, str]]] = {
    "quality": [
        {"name": "缺陷分布", "question": "统计各缺陷类型的不良数量与占比，按不良数量降序"},
        {"name": "良率趋势", "question": "按日统计最近 7 天良率趋势"},
        {"name": "周不良TOP", "question": "统计最近 7 天不良数量最多的工序 TOP5"},
    ],
    "production": [
        {"name": "产量趋势", "question": "按日统计最近 7 天总产量趋势"},
        {"name": "产线对比", "question": "统计最近 7 天各产线总产量对比"},
    ],
    "equipment": [
        {"name": "停机TOP", "question": "统计最近 7 天停机总时长最长的设备 TOP5"},
        {"name": "设备异常", "question": "统计最近 7 天各设备报警次数与停机次数汇总"},
    ],
    # 库存主题（T-015 落地后真链路可用；表名写入问题引导 NL2SQL，缺表时错误可读不崩）
    # 对齐 a07-data/sql/06_orders_inventory_ddl.sql：inventory_records（库存日快照）+
    # production_orders（生产工单）；口径见 DDL 注释与 docs/03 §3.4。
    "inventory": [
        {
            "name": "库存周转概览",
            "question": (
                "基于库存日快照表 inventory_records，统计最近 30 天各仓库出入库总量"
                "与日均期末库存，估算库存周转率概览（周转≈周期出库总量/日均库存）"
            ),
        },
        {
            "name": "库存余额分布",
            "question": (
                "基于库存日快照表 inventory_records，统计各仓库各产品最新一日的"
                "期末库存数量分布，按库存数量降序"
            ),
        },
        {
            "name": "工单完成概览",
            "question": (
                "基于生产工单表 production_orders，统计最近 30 天各产线工单"
                "计划数量合计、完成数量合计与完成率（完成率=完成合计/计划合计）"
            ),
        },
    ],
}

# general/None 兜底：以生产+质量主表为核心的通用查询集
_TOPIC_FALLBACK: list[dict[str, str]] = [
    {"name": "产量趋势", "question": "按日统计最近 7 天总产量趋势"},
    {"name": "良率趋势", "question": "按日统计最近 7 天良率趋势"},
]

BUILDER_ROWS_LIMIT = 50          # 进入报告输入/叙述的单步明细行数上限
MAX_REGENERATE = 1               # 数字校验失败重生成次数上限（计划 §13.2：≤1 次）
TOLERANCE_RATIO = 0.005          # 数字溯源容差 0.5%


def report_query_set(topic: str | None) -> list[dict[str, str]]:
    """按主题取固定查询集；general/None/未知主题走通用兜底集。"""
    if topic in TOPIC_QUERY_SETS:
        return TOPIC_QUERY_SETS[topic]
    return _TOPIC_FALLBACK


def report_id() -> str:
    """报告 ID（report 事件与 done 存档共用）。"""
    import uuid

    return f"rpt_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"


# ---- 数字一致性校验（ADR-3 核心）----

_DATE_TIME_RE = re.compile(
    r"\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?([ T]\d{1,2}:\d{2}(:\d{2})?)?"
    r"|\d{1,2}:\d{2}(:\d{2})?"
)
# 时间表述豁免（"7 天""最近 30 天"）；不含"个百分点"——其前数字须参与溯源校验
_TIME_WORD_RE = re.compile(r"\d+\s*(?:天|日|号|周|个月|月|年|小时|分钟|秒钟|秒)")
_LINE_NUMBERING_RE = re.compile(r"^\s*(?:[-*+]\s*)?\d{1,2}[.、)]\s*")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().rstrip("%").replace(",", "")
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _allowed_values(steps: list[dict[str, Any]]) -> list[float]:
    """溯源语料：steps 中全部 rows/stats 数值（质检口径：报告数字只准来自这里）。"""
    values: list[float] = []
    for step in steps:
        if not step.get("ok"):
            continue
        for row in step.get("rows") or []:
            if isinstance(row, dict):
                for value in row.values():
                    f = _to_float(value)
                    if f is not None:
                        values.append(f)
        for value in (step.get("stats") or {}).values():
            f = _to_float(value)
            if f is not None:
                values.append(f)
    return values


def _build_allowed_set(steps: list[dict[str, Any]], extra_values: list[float] | None = None) -> list[float]:
    """允许集 = 语料值 ∪ 指标合计（由数据确定性计算，属合法聚合）∪ 两两|差值|/合计 ∪
    两两比值×100（合法比较放行），排序供二分。编造数字不在其中。"""
    values = _allowed_values(steps)
    allowed = set(values)
    allowed.update(_metric_sums(steps))
    allowed.update(extra_values or [])
    if len(values) <= 800:
        n = len(values)
        for i in range(n):
            for j in range(i + 1, n):
                allowed.add(abs(values[i] - values[j]))
                allowed.add(abs(values[i] + values[j]))
                if values[j]:
                    allowed.add(abs(values[i] / values[j]) * 100)
                if values[i]:
                    allowed.add(abs(values[j] / values[i]) * 100)
    return sorted(allowed)


def _metric_sums(steps: list[dict[str, Any]]) -> list[float]:
    """各 ok 步骤各数值列的合计——由本模块确定性计算，属合法报告数字（进溯源语料）。"""
    sums: list[float] = []
    for step in steps:
        if not step.get("ok"):
            continue
        rows = [r for r in (step.get("rows") or []) if isinstance(r, dict)]
        for col in step.get("columns") or []:
            values = [v for r in rows if (v := _to_float(r.get(col))) is not None]
            if values:
                sums.append(sum(values))
    return sums


def _extract_numbers(text: str) -> list[float]:
    """提取待校验数值：先剥离日期/时间与"7 天"类时间表述、行首序号，个位数豁免。"""
    cleaned = _DATE_TIME_RE.sub(" ", text)
    cleaned = _TIME_WORD_RE.sub(" ", cleaned)
    lines = [_LINE_NUMBERING_RE.sub(" ", line) for line in cleaned.splitlines()]
    numbers = []
    for match in _NUM_RE.findall("\n".join(lines)):
        f = float(match)
        if f >= 10:  # 个位结构数（TOP5/第1步等）不校验，避免误伤
            numbers.append(f)
    return numbers


def _fmt_num_list(numbers: list[float]) -> list[str]:
    return [n.__format__("g") for n in numbers]


def verify_report_numbers(
    markdown: str, steps: list[dict[str, Any]], extra_values: list[float] | None = None
) -> list[str]:
    """提取 markdown 中全部数值逐一溯源（容差 0.5%）；返回编造嫌疑数字字符串列表。"""
    allowed = _build_allowed_set(steps, extra_values)
    eps = 1e-9
    violations: list[str] = []
    for num in _extract_numbers(markdown):
        window_lo = num * (1 - TOLERANCE_RATIO) - eps
        window_hi = num * (1 + TOLERANCE_RATIO) + eps
        lo = bisect_left(allowed, window_lo)
        if lo < len(allowed) and allowed[lo] <= window_hi:
            continue
        violations.append(num.__format__("g"))
    return violations


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])")


def sanitize_report(
    markdown: str, steps: list[dict[str, Any]], extra_values: list[float] | None = None
) -> tuple[str, list[str]]:
    """剔除含编造数字的句子；返回 (清理后 markdown, 告警列表)。"""
    violations = set(verify_report_numbers(markdown, steps, extra_values))
    if not violations:
        return markdown, []
    warnings: list[str] = []
    out_lines: list[str] = []
    for line in markdown.splitlines():
        line_nums = set(_fmt_num_list(_extract_numbers(line)))
        if not (line_nums & violations):
            out_lines.append(line)
            continue
        kept: list[str] = []
        for sentence in _SENTENCE_SPLIT_RE.split(line):
            if not sentence.strip():
                continue
            sentence_nums = set(_fmt_num_list(_extract_numbers(sentence))) & violations
            if sentence_nums:
                warnings.append(
                    "已剔除含无法溯源数字（" + "、".join(sorted(sentence_nums)) + "）的语句："
                    + sentence.strip()[:80]
                )
            else:
                kept.append(sentence)
        if "".join(kept).strip():
            out_lines.append("".join(kept))
    return "\n".join(out_lines), warnings


# ---- LLM 叙述（只叙述，不产数；输入=各步结果 JSON）----


def _strip_fence(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", (text or "").strip(), flags=re.DOTALL)
    return match.group(1).strip() if match else (text or "").strip()


def _steps_brief(steps: list[dict[str, Any]]) -> str:
    brief = []
    for step in steps:
        if not step.get("ok"):
            continue
        brief.append(
            {
                "name": step.get("name"),
                "description": step.get("description"),
                "rowCount": (step.get("stats") or {}).get("rowCount"),
                "columns": step.get("columns"),
                "rows": (step.get("rows") or [])[:BUILDER_ROWS_LIMIT],
            }
        )
    return json.dumps(brief, ensure_ascii=False, default=str)


def _llm_narrative(llm: Any, question: str, steps: list[dict[str, Any]], feedback: list[str] | None = None) -> dict[str, str] | None:
    """LLM 叙述三小节；输出非法/模型失败返回 None（走确定性兜底，不阻塞报告）。"""
    messages = [
        {"role": "system", "content": REPORT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"报告问题：{question}\n\n各查询步骤执行结果 JSON（数字只准来自这里）：\n{_steps_brief(steps)}",
        },
    ]
    if feedback:
        messages = [
            *messages,
            {
                "role": "user",
                "content": "上一稿中以下数字无法在结果 JSON 中溯源，属编造嫌疑："
                + "、".join(feedback)
                + "。请重写三节，只使用结果 JSON 中出现的数字，没有数字依据就写定性描述。",
            },
        ]
    try:
        resp = llm.chat(messages, model_tier="heavy")
        data = json.loads(_strip_fence(resp.content or ""))
        if not isinstance(data, dict):
            return None
        narrative = {key: str(data.get(key) or "").strip() for key in ("findings", "anomalies", "suggestions")}
        if not any(narrative.values()):
            return None
        return narrative
    except Exception as exc:  # LLM 失败/JSON 非法 → 兜底路径（docs/03 §6），不裸抛
        logger.warning("report_narrative_fallback error=%s", exc)
        return None


# ---- 确定性内容拼装 ----


def _fmt_num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(round(value, 4))


def _time_range_text(question: str) -> str:
    """从问题解析时间范围的展示文本（仅用于报告第四节；不影响任何查询）。"""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    if "本周" in question:
        return f"本周（{monday.isoformat()} 至 {today.isoformat()}）"
    if "本月" in question or "月报" in question:
        return f"本月（{today.replace(day=1).isoformat()} 至 {today.isoformat()}）"
    match = re.search(r"(?:最近|近)\s*(\d{1,3})\s*天", question)
    if match:
        days = int(match.group(1))
        return f"最近 {days} 天（{(today - timedelta(days=days - 1)).isoformat()} 至 {today.isoformat()}）"
    return "未明确指定（以各查询步骤的实际筛选条件为准）"


def _numeric_column(steps_row: dict[str, Any], columns: list[str]) -> str | None:
    for col in columns:
        if col in steps_row and _to_float(steps_row[col]) is not None:
            return col
    return None


def key_findings(steps: list[dict[str, Any]]) -> list[str]:
    """确定性关键发现（数字全部来自 steps），供报告兜底叙述与 done.insights 使用。"""
    findings: list[str] = []
    for step in steps:
        if not step.get("ok"):
            continue
        rows = [r for r in (step.get("rows") or []) if isinstance(r, dict)]
        columns = list(step.get("columns") or [])
        col = rows and _numeric_column(rows[0], columns)
        if not col:
            continue
        values = [f for r in rows if (f := _to_float(r.get(col))) is not None]
        if not values:
            continue
        total = sum(values)
        findings.append(
            f"{step.get('name')}：{col} 合计 {_fmt_num(total)}"
            f"（明细 {len(values)} 行，最高 {_fmt_num(max(values))}、最低 {_fmt_num(min(values))}）。"
        )
    return findings


def _deterministic_narrative(steps: list[dict[str, Any]]) -> dict[str, str]:
    findings = " ".join(key_findings(steps)) or "各查询步骤已完成，结果见对应表格。"
    anomalies_parts: list[str] = []
    for step in steps:
        if not step.get("ok"):
            continue
        rows = [r for r in (step.get("rows") or []) if isinstance(r, dict)]
        columns = list(step.get("columns") or [])
        col = rows and _numeric_column(rows[0], columns)
        if not col or len(rows) < 2:
            continue
        values = [f for r in rows if (f := _to_float(r.get(col))) is not None]
        if len(values) >= 2:
            anomalies_parts.append(
                f"{step.get('name')}中 {col} 最高 {_fmt_num(max(values))}、最低 {_fmt_num(min(values))}，"
                f"差距 {_fmt_num(max(values) - min(values))}。"
            )
    anomalies = " ".join(anomalies_parts) or "未发现明显异常。"
    suggestions = "建议结合各步骤明细进一步定位波动来源，并对异常项建立跟踪与改进措施。"
    return {"findings": findings, "anomalies": anomalies, "suggestions": suggestions}


def _assemble(
    topic: str | None,
    question: str,
    steps: list[dict[str, Any]],
    narrative: dict[str, str] | None,
) -> str:
    """十小节装配：确定性小节由代码拼装，三叙述小节取 LLM 文稿或确定性兜底。"""
    narrative = narrative or _deterministic_narrative(steps)
    ok_steps = [s for s in steps if s.get("ok")]
    lines: list[str] = [
        "# 数据分析报告",
        "",
        "## 一、报告主题",
        TOPIC_NAMES.get(topic or "general", "综合分析"),
        "",
        "## 二、分析问题",
        question.strip() or "（未提供）",
        "",
        "## 三、数据来源",
        "mes_demo（MySQL 只读）；各步骤查询 SQL 见对话 SQL 卡片与执行审计日志；"
        "各步骤明细已按系统上限截断后进入本报告（完整行数见下）。",  # 不写数字：结构性常量免校验
    ]
    for step in ok_steps:
        row_count = (step.get("stats") or {}).get("rowCount")
        lines.append(f"- {step.get('name')}：{step.get('description')}（返回 {row_count} 行）")
    for step in steps:
        if not step.get("ok"):
            # 失败步骤只写可读原因首段：完整错误（含 MySQL 错误码 1146/2003 等）已随
            # step_finished 事件与 warnings 下发；错误码若进入报告正文会触发 ADR-3
            # 数字校验并被整句剔除，反而让"缺表"信息不可见（T-017）。
            raw = str(step.get("error") or "").strip()
            reason = raw.split("：")[0].strip()[:80] if raw else "查询失败"
            if not reason:
                reason = "查询失败"
            lines.append(f"- {step.get('name')}：{reason}，未纳入报告（完整原因见对话步骤时间线）")
    lines += [
        "",
        "## 四、时间范围",
        _time_range_text(question),
        "",
        "## 五、关键指标",
        "",
        "| 查询步骤 | 指标 | 数值 |",
        "|---|---|---|",
    ]
    for step in ok_steps:
        rows = [r for r in (step.get("rows") or []) if isinstance(r, dict)]
        columns = list(step.get("columns") or [])
        col = rows and _numeric_column(rows[0], columns)
        if col:
            values = [f for r in rows if (f := _to_float(r.get(col))) is not None]
            lines.append(f"| {step.get('name')} | {col} 合计 | {_fmt_num(sum(values))} |")
        else:
            lines.append(f"| {step.get('name')} | 返回行数 | {(step.get('stats') or {}).get('rowCount', len(rows))} |")
    lines += [
        "",
        "## 六、图表锚点",
    ]
    for step in ok_steps:
        lines.append(f"- {step.get('name')}：见对话中该步骤的表格与图表卡片（数据随 table/chart 事件下发）")
    lines += [
        "",
        "## 七、核心发现",
        narrative["findings"] or "（本节数字校验未通过，已省略）",
        "",
        "## 八、异常发现",
        narrative["anomalies"] or "（本节数字校验未通过，已省略）",
        "",
        "## 九、结论建议",
        narrative["suggestions"] or "（本节数字校验未通过，已省略）",
        "",
        "## 十、生成时间",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "",
    ]
    return "\n".join(lines)


# ---- 对外入口 ----


def build_report_full(
    topic: str | None, question: str, steps: list[dict[str, Any]], llm: Any | None = None
) -> tuple[str, list[str]]:
    """生成报告并执行反幻觉数字一致性校验；返回 (markdown, warnings)。

    LLM 叙述失败自动走确定性兜底；校验失败重生成 ≤1 次，仍失败剔除违规句并记 warnings。
    """
    warnings: list[str] = []
    narrative = _llm_narrative(llm, question, steps) if llm is not None else None
    markdown = _assemble(topic, question, steps, narrative)
    violations = verify_report_numbers(markdown, steps)
    if not violations:
        return markdown, warnings

    # 重生成 ≤1 次（带违规反馈）
    if llm is not None and narrative is not None:
        retry = _llm_narrative(llm, question, steps, feedback=violations)
        if retry is not None:
            retry_md = _assemble(topic, question, steps, retry)
            if not verify_report_numbers(retry_md, steps):
                return retry_md, warnings
            markdown = retry_md
            violations = verify_report_numbers(markdown, steps)

    markdown, strip_warnings = sanitize_report(markdown, steps)
    warnings.append(
        "报告数字一致性校验未通过，已剔除编造嫌疑语句：" + "、".join(sorted(set(violations)))
    )
    warnings.extend(strip_warnings)
    return markdown, warnings


def build_report(
    topic: str | None, question: str, steps: list[dict[str, Any]], llm: Any | None = None
) -> str:
    """计划 §Task 13.2 契约签名：build_report(topic, question, steps) -> Markdown。"""
    markdown, _warnings = build_report_full(topic, question, steps, llm)
    return markdown
