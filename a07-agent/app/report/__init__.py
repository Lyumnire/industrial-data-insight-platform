# AI-assisted
"""A8 报告生成器包（P2a 计划 §Task 13 / docs/03 §3.3 A8）。

build_report(topic, question, steps) -> Markdown：主题固定查询集结果 → 十小节
结构化报告；反幻觉硬规则（ADR-3）：LLM 只叙述、数字逐一生成后溯源校验（容差 0.5%）。
"""
