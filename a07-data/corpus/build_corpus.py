# AI-assisted (T-002 数据底座 v1 / T-015 数据底座补全 · 数据评测组 · 复核人: 待主控评审后填写)
# ============================================================================
# A3 检索语料构建器: 生成 a07-data/corpus/corpus.json (P1 文件语料 + T-015 两表)
# 规范来源: docs/plans/2026-09-19-P1-走通骨架.md §Task 2 Step 2.4
#           docs/tasks/T-015-数据底座补全.md
#
# 【约束 · 后续读者必读】
#   1) 本脚本不连数据库(Docker/MySQL 可选验证, 对账以静态为准): 表/列/口径定义与
#      sql/01_mes_demo_ddl.sql、sql/06_orders_inventory_ddl.sql、
#      sql/02_seed_knowledge.sql 由本文件静态镜像, 末尾自动做三方静态对账
#      (表名/指标编码/示例 SQL 标识符白名单), 修改任一侧必须同步另一侧。
#   2) corpus.json 是 a07-agent A3 检索器(P1)的加载文件, 也是 P2 向量库
#      collection 的同构结构, 字段命名不可随意变更。
#   3) examples 中"最近 N 天"以库内最新数据日期为锚点(MAX(日期列)), 不用
#      CURDATE(), 避免演示日数据过期导致查询空结果; 全部为单条 SELECT,
#      兼容 a07-agent sqlguard 校验(仅 SELECT + 强制 LIMIT)。
#   4) examples 同时提供 question(规范键名)与 q(计划 §Task 2.4 原文别名),
#      二者同值, 检索端任取其一。
#   5) 静态断言与 TABLES/METRICS/EXAMPLES 长度联动, 禁止写死表数量。
# ============================================================================

import json
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent  # a07-data/corpus/
SQL_DIR = BASE_DIR.parent / "sql"
OUT_PATH = BASE_DIR / "corpus.json"

# ---------------- 表元数据(与 01_mes_demo_ddl.sql + 06_orders_inventory_ddl.sql 一致) ----------------
TABLES: list[dict] = [
    {
        "name": "process_output",
        "comment": "工序产量表",
        "description": "按 产线x工序x产品x批次 记录每日投产/合格/不良数量, 是产量、良率、不良率类指标的主要来源(90天合成数据)",
        "columns": [
            {"name": "id", "type": "BIGINT", "comment": "主键, 自增", "samples": ["1", "2"]},
            {"name": "production_date", "type": "DATE", "comment": "生产日期", "samples": ["2026-09-18", "2026-09-17"]},
            {"name": "production_line", "type": "VARCHAR(20)", "comment": "产线编号(L1/L2/L3)", "samples": ["L1", "L2", "L3"]},
            {"name": "product_id", "type": "VARCHAR(20)", "comment": "产品编号", "samples": ["P-1001", "P-1006"]},
            {"name": "product_name", "type": "VARCHAR(50)", "comment": "产品名称", "samples": ["仪表板总成", "前保险杠"]},
            {"name": "process_name", "type": "VARCHAR(30)", "comment": "工序名(注塑/焊接/装配/喷涂/包装)", "samples": ["注塑", "焊接"]},
            {"name": "produced_qty", "type": "INT", "comment": "投产数量", "samples": ["300~900 的整数"]},
            {"name": "qualified_qty", "type": "INT", "comment": "合格数量", "samples": ["= produced_qty - defect_qty"]},
            {"name": "defect_qty", "type": "INT", "comment": "不良数量", "samples": ["0 ~ produced_qty"]},
        ],
        "relations": [
            {"from_table": "process_output", "from_column": "product_id", "to_table": "quality_inspections",
             "to_column": "product_id", "type": "logical", "description": "同一产品维度, 可与质量检验表按产品关联"},
            {"from_table": "process_output", "from_column": "production_line", "to_table": "quality_inspections",
             "to_column": "production_line", "type": "logical", "description": "同产线维度关联(可叠加 process_name 同工序)"},
            {"from_table": "process_output", "from_column": "production_line", "to_table": "equipment_downtime",
             "to_column": "production_line", "type": "logical", "description": "同产线维度, 停机与产量/良率对照分析"},
            {"from_table": "process_output", "from_column": "product_id", "to_table": "production_orders",
             "to_column": "product_id", "type": "logical", "description": "同一产品维度, 产量与工单完成情况对照"},
            {"from_table": "process_output", "from_column": "production_line", "to_table": "production_orders",
             "to_column": "production_line", "type": "logical", "description": "同产线维度, 产量与工单状态/停机对照"},
            {"from_table": "process_output", "from_column": "product_id", "to_table": "inventory_records",
             "to_column": "product_id", "type": "logical", "description": "同一产品维度, 产出与库存/出入库对照"},
        ],
    },
    {
        "name": "quality_inspections",
        "comment": "质量检验表",
        "description": "按检验批次记录检验数量与缺陷类型分布(defect_type 为空表示该批次无不良), 用于缺陷构成与质量波动分析",
        "columns": [
            {"name": "id", "type": "BIGINT", "comment": "主键, 自增", "samples": ["1", "2"]},
            {"name": "inspection_time", "type": "DATETIME", "comment": "检验时间", "samples": ["2026-09-18 08:15:23"]},
            {"name": "product_id", "type": "VARCHAR(20)", "comment": "产品编号", "samples": ["P-1001", "P-1006"]},
            {"name": "product_name", "type": "VARCHAR(50)", "comment": "产品名称", "samples": ["仪表板总成", "前保险杠"]},
            {"name": "production_line", "type": "VARCHAR(20)", "comment": "产线编号(L1/L2/L3)", "samples": ["L1", "L2", "L3"]},
            {"name": "process_name", "type": "VARCHAR(30)", "comment": "工序名(注塑/焊接/装配/喷涂/包装)", "samples": ["注塑", "焊接"]},
            {"name": "inspection_qty", "type": "INT", "comment": "检验数量", "samples": ["80~300 的整数"]},
            {"name": "qualified_qty", "type": "INT", "comment": "合格数量", "samples": ["= inspection_qty - defect_qty"]},
            {"name": "defect_qty", "type": "INT", "comment": "不良数量", "samples": ["0 ~ inspection_qty"]},
            {"name": "defect_type", "type": "VARCHAR(30)", "comment": "缺陷类型(划痕/气泡/尺寸偏差/色差/变形)", "samples": ["划痕", "气泡", "尺寸偏差"]},
        ],
        "relations": [
            {"from_table": "quality_inspections", "from_column": "product_id", "to_table": "process_output",
             "to_column": "product_id", "type": "logical", "description": "同一产品维度, 可与工序产量表按产品关联"},
            {"from_table": "quality_inspections", "from_column": "production_line", "to_table": "equipment_downtime",
             "to_column": "production_line", "type": "logical", "description": "同产线维度, 停机与质量对照分析"},
        ],
    },
    {
        "name": "equipment_downtime",
        "comment": "设备停机表",
        "description": "记录设备停机事件(起止时间/时长/原因/报警次数), 用于设备效率与异常停机分析(合成数据含 EQ-07 长停机规律)",
        "columns": [
            {"name": "id", "type": "BIGINT", "comment": "主键, 自增", "samples": ["1", "2"]},
            {"name": "equipment_id", "type": "VARCHAR(20)", "comment": "设备编号", "samples": ["EQ-01", "EQ-07", "EQ-15"]},
            {"name": "equipment_name", "type": "VARCHAR(50)", "comment": "设备名称", "samples": ["注塑机-1", "焊接机器人-2"]},
            {"name": "production_line", "type": "VARCHAR(20)", "comment": "产线编号(L1/L2/L3)", "samples": ["L1", "L2", "L3"]},
            {"name": "start_time", "type": "DATETIME", "comment": "停机开始时间", "samples": ["2026-09-18 09:30:00"]},
            {"name": "end_time", "type": "DATETIME", "comment": "停机结束时间", "samples": ["2026-09-18 11:10:00"]},
            {"name": "downtime_minutes", "type": "INT", "comment": "停机分钟数", "samples": ["10~260 的整数"]},
            {"name": "reason", "type": "VARCHAR(100)", "comment": "停机原因(故障/换型/保养/待料)", "samples": ["故障", "换型", "保养"]},
            {"name": "alarm_count", "type": "INT", "comment": "报警次数", "samples": ["0~8 的整数"]},
        ],
        "relations": [
            {"from_table": "equipment_downtime", "from_column": "production_line", "to_table": "process_output",
             "to_column": "production_line", "type": "logical", "description": "同产线维度, 停机与产量/良率对照分析"},
            {"from_table": "equipment_downtime", "from_column": "production_line", "to_table": "production_orders",
             "to_column": "production_line", "type": "logical", "description": "同产线维度, 长停机与工单暂停/延期对照(L2/EQ-07)"},
        ],
    },
    {
        "name": "production_orders",
        "comment": "生产工单表",
        "description": "每日下达的生产工单(计划/完成数量、状态、计划与实际起止日期); 未完成工单 actual_end 为 NULL。工单完成率=SUM(completed_qty)/SUM(planned_qty)。合成数据注入 R-H: L2 最近30天已暂停占比显著抬高",
        "columns": [
            {"name": "id", "type": "BIGINT", "comment": "主键, 自增", "samples": ["1", "2"]},
            {"name": "order_no", "type": "VARCHAR(30)", "comment": "工单编号(WO-日期-序号, 全表唯一)", "samples": ["WO-20260918-001"]},
            {"name": "product_id", "type": "VARCHAR(20)", "comment": "产品编号", "samples": ["P-1001", "P-1006"]},
            {"name": "product_name", "type": "VARCHAR(50)", "comment": "产品名称", "samples": ["仪表板总成", "前保险杠"]},
            {"name": "production_line", "type": "VARCHAR(20)", "comment": "产线编号(L1/L2/L3)", "samples": ["L1", "L2", "L3"]},
            {"name": "planned_qty", "type": "INT", "comment": "计划数量", "samples": ["500~2000 的整数"]},
            {"name": "completed_qty", "type": "INT", "comment": "已完成数量(不超过计划数量)", "samples": ["0 ~ planned_qty"]},
            {"name": "status", "type": "VARCHAR(10)", "comment": "工单状态(已完成/进行中/已暂停)", "samples": ["已完成", "进行中", "已暂停"]},
            {"name": "planned_start", "type": "DATE", "comment": "计划开始日期(即工单下达日)", "samples": ["2026-09-18"]},
            {"name": "planned_end", "type": "DATE", "comment": "计划完成日期", "samples": ["2026-09-22"]},
            {"name": "actual_start", "type": "DATE", "comment": "实际开始日期(下达即开工, 等于计划开始日期)", "samples": ["2026-09-18"]},
            {"name": "actual_end", "type": "DATE", "comment": "实际完成日期(进行中/已暂停为 NULL)", "samples": ["2026-09-21", "NULL"]},
        ],
        "relations": [
            {"from_table": "production_orders", "from_column": "product_id", "to_table": "process_output",
             "to_column": "product_id", "type": "logical", "description": "同一产品维度, 工单与工序产量对照"},
            {"from_table": "production_orders", "from_column": "production_line", "to_table": "process_output",
             "to_column": "production_line", "type": "logical", "description": "同产线维度, 工单状态与产量/停机对照"},
            {"from_table": "production_orders", "from_column": "production_line", "to_table": "equipment_downtime",
             "to_column": "production_line", "type": "logical", "description": "同产线维度, 工单暂停与设备长停机关联(L2)"},
            {"from_table": "production_orders", "from_column": "product_id", "to_table": "inventory_records",
             "to_column": "product_id", "type": "logical", "description": "同一产品维度, 工单产出与库存变动对照"},
        ],
    },
    {
        "name": "inventory_records",
        "comment": "库存日快照表",
        "description": "仓库x产品的每日期末库存/入库/出库快照(期末库存=昨日库存+入库-出库)。库存周转近似=SUM(outbound_qty)/AVG(inventory_qty); 安全库存预警线=日均出库x7; 呆滞=库存持续走高而出货稀少。合成数据注入 R-E/R-F/R-G",
        "columns": [
            {"name": "id", "type": "BIGINT", "comment": "主键, 自增", "samples": ["1", "2"]},
            {"name": "record_date", "type": "DATE", "comment": "快照日期", "samples": ["2026-09-18", "2026-09-17"]},
            {"name": "warehouse", "type": "VARCHAR(10)", "comment": "仓库编号(WH-01..WH-06)", "samples": ["WH-01", "WH-02", "WH-06"]},
            {"name": "product_id", "type": "VARCHAR(20)", "comment": "产品编号", "samples": ["P-1001", "P-1003"]},
            {"name": "product_name", "type": "VARCHAR(50)", "comment": "产品名称", "samples": ["仪表板总成", "车门内板"]},
            {"name": "inventory_qty", "type": "INT", "comment": "期末库存数量(当日快照)", "samples": ["0~20000 的整数"]},
            {"name": "inbound_qty", "type": "INT", "comment": "当日入库数量", "samples": ["0~400 的整数"]},
            {"name": "outbound_qty", "type": "INT", "comment": "当日出库数量", "samples": ["8~400 的整数"]},
        ],
        "relations": [
            {"from_table": "inventory_records", "from_column": "product_id", "to_table": "process_output",
             "to_column": "product_id", "type": "logical", "description": "同一产品维度, 库存与产量/需求对照"},
            {"from_table": "inventory_records", "from_column": "product_id", "to_table": "production_orders",
             "to_column": "product_id", "type": "logical", "description": "同一产品维度, 库存与工单完成情况对照"},
            {"from_table": "inventory_records", "from_column": "product_id", "to_table": "quality_inspections",
             "to_column": "product_id", "type": "logical", "description": "同一产品维度, 库存与质量批次可关联"},
        ],
    },
]

# ---------------- 指标口径(与 sql/02_seed_knowledge.sql 的 v_metric 种子一致) ----------------
METRICS: list[dict] = [
    {"name": "产量", "code": "output_qty", "description": "统计周期内各产线/工序/产品的投产数量总和",
     "formula_sql": "SUM(produced_qty)", "unit": "件", "business_domain": "生产",
     "source_tables": "process_output", "source_columns": "process_output.produced_qty"},
    {"name": "合格数", "code": "qualified_qty", "description": "统计周期内合格数量总和",
     "formula_sql": "SUM(qualified_qty)", "unit": "件", "business_domain": "质量",
     "source_tables": "process_output", "source_columns": "process_output.qualified_qty"},
    {"name": "不良数", "code": "defect_qty", "description": "统计周期内不良数量总和",
     "formula_sql": "SUM(defect_qty)", "unit": "件", "business_domain": "质量",
     "source_tables": "process_output", "source_columns": "process_output.defect_qty"},
    {"name": "工序良率", "code": "process_yield_rate", "description": "良率=合格数/投产数, 须先按维度求和再相除, 禁止对行级比率求平均",
     "formula_sql": "SUM(qualified_qty)/NULLIF(SUM(produced_qty),0)", "unit": "%", "business_domain": "质量",
     "source_tables": "process_output", "source_columns": "process_output.qualified_qty,process_output.produced_qty"},
    {"name": "不良率", "code": "defect_rate", "description": "不良率=不良数/投产数, 与良率互补, 同样先求和再相除",
     "formula_sql": "SUM(defect_qty)/NULLIF(SUM(produced_qty),0)", "unit": "%", "business_domain": "质量",
     "source_tables": "process_output", "source_columns": "process_output.defect_qty,process_output.produced_qty"},
    {"name": "停机时长", "code": "downtime_minutes", "description": "统计周期内设备停机分钟数总和, 可按设备/产线/原因分组",
     "formula_sql": "SUM(downtime_minutes)", "unit": "分钟", "business_domain": "设备",
     "source_tables": "equipment_downtime", "source_columns": "equipment_downtime.downtime_minutes"},
    # ---- T-015 工单/库存指标(口径与 06_orders_inventory_ddl.sql 注释一致) ----
    {"name": "工单数量", "code": "order_count",
     "description": "统计周期内工单条数, 可按状态/产线/产品分组(已暂停占比=R-H 演示口径)",
     "formula_sql": "COUNT(*)", "unit": "单", "business_domain": "生产",
     "source_tables": "production_orders", "source_columns": "production_orders.order_no"},
    {"name": "工单完成率", "code": "order_completion_rate",
     "description": "完成率=已完成数量/计划数量, 须先对 completed_qty 与 planned_qty 求和再相除, 禁止对行级完成率求平均",
     "formula_sql": "SUM(completed_qty)/NULLIF(SUM(planned_qty),0)", "unit": "%", "business_domain": "生产",
     "source_tables": "production_orders",
     "source_columns": "production_orders.completed_qty,production_orders.planned_qty"},
    {"name": "期末库存", "code": "inventory_qty",
     "description": "库存日快照的期末库存数量; 按仓库/产品统计时取最新一日或周期均值",
     "formula_sql": "SUM(inventory_qty)", "unit": "件", "business_domain": "库存",
     "source_tables": "inventory_records", "source_columns": "inventory_records.inventory_qty"},
    {"name": "入库量", "code": "inbound_qty",
     "description": "统计周期内各仓库/产品的入库数量总和",
     "formula_sql": "SUM(inbound_qty)", "unit": "件", "business_domain": "库存",
     "source_tables": "inventory_records", "source_columns": "inventory_records.inbound_qty"},
    {"name": "出库量", "code": "outbound_qty",
     "description": "统计周期内各仓库/产品的出库数量总和",
     "formula_sql": "SUM(outbound_qty)", "unit": "件", "business_domain": "库存",
     "source_tables": "inventory_records", "source_columns": "inventory_records.outbound_qty"},
    {"name": "库存周转次数", "code": "inventory_turnover",
     "description": "近似口径=周期出库总量/日均库存, 日均库存以 AVG(inventory_qty) 近似",
     "formula_sql": "SUM(outbound_qty)/NULLIF(AVG(inventory_qty),0)", "unit": "次", "business_domain": "库存",
     "source_tables": "inventory_records",
     "source_columns": "inventory_records.outbound_qty,inventory_records.inventory_qty"},
    {"name": "安全库存预警线", "code": "safety_stock_line",
     "description": "样例库约定: 安全库存=该产品日均出库量x7; 期末库存低于该线视为缺货风险(如 P-1001 近14天)",
     "formula_sql": "AVG(outbound_qty)*7", "unit": "件", "business_domain": "库存",
     "source_tables": "inventory_records",
     "source_columns": "inventory_records.outbound_qty,inventory_records.inventory_qty"},
]

# ---------------- 示例问答对(覆盖 01-需求分析.md §7 场景 + T-015 库存/工单主题) ----------------
EXAMPLES: list[dict] = [
    {"question": "请分析各工序的良率。",
     "sql": "SELECT process_name, ROUND(SUM(qualified_qty) / NULLIF(SUM(produced_qty), 0) * 100, 2) AS yield_rate FROM process_output GROUP BY process_name ORDER BY yield_rate"},
    {"question": "找出最近30天不良数量最高的产品。",
     "sql": "SELECT product_id, product_name, SUM(defect_qty) AS total_defect_qty FROM process_output WHERE production_date >= DATE_SUB((SELECT MAX(production_date) FROM process_output), INTERVAL 29 DAY) GROUP BY product_id, product_name ORDER BY total_defect_qty DESC LIMIT 10"},
    {"question": "统计每条产线最近7天的产量趋势。",
     "sql": "SELECT production_date, production_line, SUM(produced_qty) AS daily_output FROM process_output WHERE production_date >= DATE_SUB((SELECT MAX(production_date) FROM process_output), INTERVAL 6 DAY) GROUP BY production_date, production_line ORDER BY production_date, production_line"},
    {"question": "分析不同缺陷类型的分布。",
     "sql": "SELECT defect_type, COUNT(*) AS inspection_cnt, SUM(defect_qty) AS defect_qty_total FROM quality_inspections WHERE defect_type IS NOT NULL AND defect_type <> '' GROUP BY defect_type ORDER BY defect_qty_total DESC"},
    {"question": "找出最近30天停机时间最长的设备 top5。",
     "sql": "SELECT equipment_id, equipment_name, production_line, COUNT(*) AS downtime_events, SUM(downtime_minutes) AS total_downtime_minutes FROM equipment_downtime WHERE start_time >= DATE_SUB((SELECT MAX(start_time) FROM equipment_downtime), INTERVAL 29 DAY) GROUP BY equipment_id, equipment_name, production_line ORDER BY total_downtime_minutes DESC LIMIT 5"},
    {"question": "统计最近30天各产品的不良率。",
     "sql": "SELECT product_id, product_name, ROUND(SUM(defect_qty) / NULLIF(SUM(produced_qty), 0) * 100, 2) AS defect_rate FROM process_output WHERE production_date >= DATE_SUB((SELECT MAX(production_date) FROM process_output), INTERVAL 29 DAY) GROUP BY product_id, product_name ORDER BY defect_rate DESC"},
    # ---- T-015: 工单/库存主题(库存呆滞、工单完成率、安全库存、暂停工单、周五出库、周转) ----
    {"question": "统计最近30天各产线的工单完成率。",
     "sql": "SELECT production_line, ROUND(SUM(completed_qty) / NULLIF(SUM(planned_qty), 0) * 100, 2) AS order_completion_rate FROM production_orders WHERE planned_start >= DATE_SUB((SELECT MAX(planned_start) FROM production_orders), INTERVAL 29 DAY) GROUP BY production_line ORDER BY order_completion_rate"},
    {"question": "找出近60天库存偏高且出货稀少的产品(库存呆滞风险)。",
     "sql": "SELECT product_id, product_name, ROUND(AVG(inventory_qty), 0) AS avg_stock, ROUND(AVG(outbound_qty), 1) AS avg_outbound FROM inventory_records WHERE record_date >= DATE_SUB((SELECT MAX(record_date) FROM inventory_records), INTERVAL 59 DAY) GROUP BY product_id, product_name ORDER BY avg_stock DESC, avg_outbound ASC LIMIT 10"},
    {"question": "找出近14天期末库存跌破安全库存线的产品(安全库存=日均出库量乘7)。",
     "sql": "SELECT product_id, product_name, MIN(inventory_qty) AS min_stock, ROUND(AVG(outbound_qty) * 7, 0) AS safety_stock_line FROM inventory_records WHERE record_date >= DATE_SUB((SELECT MAX(record_date) FROM inventory_records), INTERVAL 13 DAY) GROUP BY product_id, product_name HAVING min_stock < safety_stock_line ORDER BY min_stock LIMIT 10"},
    {"question": "统计最近30天各产线工单数量与已暂停工单数。",
     "sql": "SELECT production_line, COUNT(*) AS total_orders, SUM(CASE WHEN status = '已暂停' THEN 1 ELSE 0 END) AS paused_orders FROM production_orders WHERE planned_start >= DATE_SUB((SELECT MAX(planned_start) FROM production_orders), INTERVAL 29 DAY) GROUP BY production_line ORDER BY paused_orders DESC LIMIT 5"},
    {"question": "分析WH-02仓库最近30天各星期几的平均出库量(查看周五出库高峰)。",
     "sql": "SELECT warehouse, WEEKDAY(record_date) AS weekday_num, ROUND(AVG(outbound_qty), 1) AS avg_outbound FROM inventory_records WHERE warehouse = 'WH-02' AND record_date >= DATE_SUB((SELECT MAX(record_date) FROM inventory_records), INTERVAL 29 DAY) GROUP BY warehouse, WEEKDAY(record_date) ORDER BY weekday_num LIMIT 7"},
    {"question": "计算最近30天各产品的库存周转次数近似值。",
     "sql": "SELECT product_id, product_name, ROUND(SUM(outbound_qty) / NULLIF(AVG(inventory_qty), 0), 2) AS inventory_turnover FROM inventory_records WHERE record_date >= DATE_SUB((SELECT MAX(record_date) FROM inventory_records), INTERVAL 29 DAY) GROUP BY product_id, product_name ORDER BY inventory_turnover DESC LIMIT 10"},
]
# 与 EXAMPLES 按下标一一对应的静态自查信息: 示例使用的表 + SQL 中出现的别名
EXAMPLE_CHECKS: list[dict] = [
    {"tables": ["process_output"], "aliases": ["yield_rate"]},
    {"tables": ["process_output"], "aliases": ["total_defect_qty"]},
    {"tables": ["process_output"], "aliases": ["daily_output"]},
    {"tables": ["quality_inspections"], "aliases": ["inspection_cnt", "defect_qty_total"]},
    {"tables": ["equipment_downtime"], "aliases": ["downtime_events", "total_downtime_minutes"]},
    {"tables": ["process_output"], "aliases": ["defect_rate"]},
    {"tables": ["production_orders"], "aliases": ["order_completion_rate"]},
    {"tables": ["inventory_records"], "aliases": ["avg_stock", "avg_outbound"]},
    {"tables": ["inventory_records"], "aliases": ["min_stock", "safety_stock_line"]},
    {"tables": ["production_orders"], "aliases": ["total_orders", "paused_orders"]},
    {"tables": ["inventory_records"], "aliases": ["weekday_num", "avg_outbound"]},
    {"tables": ["inventory_records"], "aliases": ["inventory_turnover"]},
]

# 示例 SQL 中允许出现的 SQL 关键词/函数(小写)
SQL_KEYWORDS = {
    "select", "from", "where", "group", "by", "order", "limit", "as", "and", "or",
    "not", "null", "is", "in", "on", "desc", "asc", "distinct", "having",
    "interval", "day", "sum", "count", "round", "max", "min", "avg",
    "date_sub", "nullif", "case", "when", "then", "else", "end", "weekday",
}


def build_m_schema(t: dict) -> str:
    """M-Schema 风格 markdown: 表注释 + 每列 类型/注释(供 LLM 理解 schema)。"""
    lines = ["### %s（%s）" % (t["name"], t["comment"]), "", t["description"], "",
             "| 列名 | 类型 | 注释 |", "|---|---|---|"]
    lines += ["| %s | %s | %s |" % (c["name"], c["type"], c["comment"]) for c in t["columns"]]
    return "\n".join(lines)


def check_example_sql(sql: str, used_tables: list[str], aliases: list[str]) -> None:
    """示例 SQL 静态自查(不连库): 限定列引用与全部标识符必须在已知表列/关键词/别名白名单内。
    真实可运行性仍需人工核对列名 + 实库验证(工单约束)。
    字符串字面量(如 'WH-02'/'已暂停')不参与标识符白名单检查。"""
    tmap = {t["name"]: {c["name"] for c in t["columns"]} for t in TABLES}
    for tn in used_tables:
        assert tn in tmap, "示例引用了未知表: %s" % tn
    for m in re.finditer(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b", sql):
        t, c = m.group(1), m.group(2)
        assert t in tmap and c in tmap[t], "限定列引用不存在: %s.%s" % (t, c)
    allowed = set().union(*(tmap[t] for t in used_tables)) | set(tmap) | SQL_KEYWORDS | set(aliases)
    sql_no_str = re.sub(r"'[^']*'", " ", sql)
    for tok in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", sql_no_str):
        assert tok.lower() in allowed, "示例 SQL 出现未知标识符 [%s] in %s" % (tok, sql[:50])


def main() -> int:
    # 1) 与 DDL 静态对账: 表名集合一致(01 原三表 + 06 增补两表), 每个列名都出现在对应 DDL 文本中
    ddl_text = ((SQL_DIR / "01_mes_demo_ddl.sql").read_text(encoding="utf-8")
                + "\n" + (SQL_DIR / "06_orders_inventory_ddl.sql").read_text(encoding="utf-8"))
    ddl_tables = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", ddl_text))
    corpus_table_names = {t["name"] for t in TABLES}
    assert ddl_tables == corpus_table_names, \
        "corpus 表名与 DDL 不一致: %s" % (ddl_tables ^ corpus_table_names)
    for t in TABLES:
        for c in t["columns"]:
            assert c["name"] in ddl_text, "列 %s 未出现在 01/06 DDL 中" % c["name"]

    # 2) 与指标种子静态对账: v_metric INSERT 元组第二个引号字段即指标编码
    seed_text = (SQL_DIR / "02_seed_knowledge.sql").read_text(encoding="utf-8")
    seed_codes = set(re.findall(r"\(\s*'[^']+'\s*,\s*'([a-z0-9_]+)'\s*,", seed_text))
    corpus_codes = {m["code"] for m in METRICS}
    assert seed_codes == corpus_codes, "指标编码与 02_seed_knowledge.sql 不一致: %s" % (seed_codes ^ corpus_codes)

    # 3) 示例对静态自查: 数量与 EXAMPLE_CHECKS 对齐, 且标识符白名单通过
    assert len(EXAMPLES) >= 5, "示例问答对不足 5 条"
    assert len(EXAMPLES) == len(EXAMPLE_CHECKS), "EXAMPLES 与 EXAMPLE_CHECKS 长度不一致"
    for ex, chk in zip(EXAMPLES, EXAMPLE_CHECKS):
        check_example_sql(ex["sql"], chk["tables"], chk["aliases"])

    # 4) 组装并写出 corpus.json, 回读验证 json 可解析(数量与源常量联动, 不写死)
    tables_out = []
    for t in TABLES:
        tables_out.append({
            "name": t["name"], "comment": t["comment"], "description": t["description"],
            "ddl_m_schema": build_m_schema(t), "columns": t["columns"], "relations": t["relations"],
        })
    corpus = {
        "version": "t015-v1",
        "description": "A07 检索语料: 由 a07-data/corpus/build_corpus.py 生成(T-015 含生产工单/库存两表), a07-agent A3 检索器加载; P2 向量库 collection 同构",
        "tables": tables_out,
        "metrics": METRICS,
        "examples": [{"question": ex["question"], "q": ex["question"], "sql": ex["sql"]} for ex in EXAMPLES],
    }
    OUT_PATH.write_text(json.dumps(corpus, ensure_ascii=False, indent=2), encoding="utf-8")
    loaded = json.loads(OUT_PATH.read_text(encoding="utf-8"))  # 验收标准: json.load 可解析
    assert len(loaded["tables"]) == len(TABLES)
    assert len(loaded["metrics"]) == len(METRICS)
    assert len(loaded["examples"]) == len(EXAMPLES)

    print("[OK] corpus.json 已生成: %s" % OUT_PATH)
    print("  tables=%d (%s)" % (len(loaded["tables"]), "/".join(t["name"] for t in loaded["tables"])))
    print("  metrics=%d (编码与 02_seed_knowledge.sql 静态对账一致)" % len(loaded["metrics"]))
    print("  examples=%d (标识符白名单静态自查通过)" % len(loaded["examples"]))
    print("  relations: " + ", ".join("%s:%d" % (t["name"], len(t["relations"])) for t in loaded["tables"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
