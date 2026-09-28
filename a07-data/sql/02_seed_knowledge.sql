-- AI-assisted (T-002 数据底座 v1 · 数据评测组 · 复核人: 待主控评审后填写)
-- ============================================================================
-- a07_platform 平台库 P1 最小表 + 业务指标口径种子(语义层)
-- 规范来源: docs/plans/2026-09-19-P1-走通骨架.md §Task 2 Step 2.2(工单笔误应为 Step 2.3)
-- 说明:
--   * P1 只建最小知识表 v_metric / v_table_meta; 完整"知识四实体 + 元数据七表"
--     见 docs/03-架构与模块设计.md §3.4, 在 P2 由平台库 Flyway 基线补齐。
--   * v_metric 的 6 条指标口径与 a07-data/corpus/build_corpus.py 中的 METRICS
--     一致(该脚本末尾会做编码集合静态对账), 修改任一侧必须同步另一侧。
-- ============================================================================

CREATE DATABASE IF NOT EXISTS a07_platform DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE a07_platform;

-- 业务指标口径表: formula_sql 为可直接展开的 SQL 片段(NL2SQL 指标口径优先引用)
CREATE TABLE IF NOT EXISTS v_metric (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(50) NOT NULL COMMENT '指标名称(中文)',
  code VARCHAR(50) NOT NULL COMMENT '指标编码(英文, 唯一)',
  description VARCHAR(200) NOT NULL COMMENT '指标业务含义与口径说明',
  formula_sql VARCHAR(500) NOT NULL COMMENT '计算公式(SQL 片段)',
  unit VARCHAR(20) NOT NULL COMMENT '计量单位',
  business_domain VARCHAR(20) NOT NULL COMMENT '业务域(生产/质量/设备)',
  source_tables VARCHAR(200) NOT NULL COMMENT '来源表(逗号分隔)',
  source_columns VARCHAR(500) NOT NULL COMMENT '来源字段(逗号分隔)',
  UNIQUE KEY uk_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='业务指标口径表(P1语义层种子)';

-- 业务表元数据表: P1 最小版, 完整元数据模型(table_metadata/column_metadata 等)在 P2
CREATE TABLE IF NOT EXISTS v_table_meta (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  table_name VARCHAR(64) NOT NULL COMMENT '业务库表名',
  description VARCHAR(200) NOT NULL COMMENT '表业务含义',
  columns_json TEXT NOT NULL COMMENT '列元数据 JSON 数组, 元素结构 {name,type,comment}',
  UNIQUE KEY uk_table (table_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='业务表元数据表(P1最小版)';

-- ---------------------------------------------------------------------------
-- 指标口径种子(T-015 后共 12 条): 原 6 条 + 工单/库存 6 条
-- 注意: 工序良率/工单完成率/库存周转等比率必须"先聚合再相除", 不可对行级比率求平均
-- 与 a07-data/corpus/build_corpus.py 的 METRICS 静态对账(改任一侧须同步)。
-- 变更申请: a07-server V2__knowledge.sql 的 business_metrics 仍为原 6 条,
--   topic_inventory.related_metric_ids 为空, 请主控/Java 组按下方编码同步平台库种子。
-- ---------------------------------------------------------------------------
INSERT INTO v_metric (name, code, description, formula_sql, unit, business_domain, source_tables, source_columns) VALUES
('产量', 'output_qty', '统计周期内各产线/工序/产品的投产数量总和', 'SUM(produced_qty)', '件', '生产', 'process_output', 'process_output.produced_qty'),
('合格数', 'qualified_qty', '统计周期内合格数量总和', 'SUM(qualified_qty)', '件', '质量', 'process_output', 'process_output.qualified_qty'),
('不良数', 'defect_qty', '统计周期内不良数量总和', 'SUM(defect_qty)', '件', '质量', 'process_output', 'process_output.defect_qty'),
('工序良率', 'process_yield_rate', '良率=合格数/投产数, 须先按维度求和再相除, 禁止对行级比率求平均', 'SUM(qualified_qty)/NULLIF(SUM(produced_qty),0)', '%', '质量', 'process_output', 'process_output.qualified_qty,process_output.produced_qty'),
('不良率', 'defect_rate', '不良率=不良数/投产数, 与良率互补, 同样先求和再相除', 'SUM(defect_qty)/NULLIF(SUM(produced_qty),0)', '%', '质量', 'process_output', 'process_output.defect_qty,process_output.produced_qty'),
('停机时长', 'downtime_minutes', '统计周期内设备停机分钟数总和, 可按设备/产线/原因分组', 'SUM(downtime_minutes)', '分钟', '设备', 'equipment_downtime', 'equipment_downtime.downtime_minutes'),
('工单数量', 'order_count', '统计周期内工单条数, 可按状态/产线/产品分组(已暂停占比=R-H 演示口径)', 'COUNT(*)', '单', '生产', 'production_orders', 'production_orders.order_no'),
('工单完成率', 'order_completion_rate', '完成率=已完成数量/计划数量, 须先对 completed_qty 与 planned_qty 求和再相除, 禁止对行级完成率求平均(与 06 DDL 注释一致)', 'SUM(completed_qty)/NULLIF(SUM(planned_qty),0)', '%', '生产', 'production_orders', 'production_orders.completed_qty,production_orders.planned_qty'),
('期末库存', 'inventory_qty', '库存日快照的期末库存数量; 按仓库/产品统计时取最新一日或周期均值', 'SUM(inventory_qty)', '件', '库存', 'inventory_records', 'inventory_records.inventory_qty'),
('入库量', 'inbound_qty', '统计周期内各仓库/产品的入库数量总和', 'SUM(inbound_qty)', '件', '库存', 'inventory_records', 'inventory_records.inbound_qty'),
('出库量', 'outbound_qty', '统计周期内各仓库/产品的出库数量总和', 'SUM(outbound_qty)', '件', '库存', 'inventory_records', 'inventory_records.outbound_qty'),
('库存周转次数', 'inventory_turnover', '近似口径=周期出库总量/日均库存, 日均库存以 AVG(inventory_qty) 近似(与 06 DDL 注释一致)', 'SUM(outbound_qty)/NULLIF(AVG(inventory_qty),0)', '次', '库存', 'inventory_records', 'inventory_records.outbound_qty,inventory_records.inventory_qty'),
('安全库存预警线', 'safety_stock_line', '样例库约定: 安全库存=该产品日均出库量x7; 期末库存低于该线视为缺货风险(如 P-1001 近14天)', 'AVG(outbound_qty)*7', '件', '库存', 'inventory_records', 'inventory_records.outbound_qty,inventory_records.inventory_qty');

-- ---------------------------------------------------------------------------
-- 表元数据种子(5 张业务表): columns_json 与 01/06 DDL 列定义一致
-- ---------------------------------------------------------------------------
INSERT INTO v_table_meta (table_name, description, columns_json) VALUES
('process_output', '工序产量表: 产线x工序x产品x批次的每日投产/合格/不良数量, 产量与良率类指标主要来源', '[{"name":"id","type":"BIGINT","comment":"主键, 自增"},{"name":"production_date","type":"DATE","comment":"生产日期"},{"name":"production_line","type":"VARCHAR(20)","comment":"产线编号(L1/L2/L3)"},{"name":"product_id","type":"VARCHAR(20)","comment":"产品编号"},{"name":"product_name","type":"VARCHAR(50)","comment":"产品名称"},{"name":"process_name","type":"VARCHAR(30)","comment":"工序名(注塑/焊接/装配/喷涂/包装)"},{"name":"produced_qty","type":"INT","comment":"投产数量"},{"name":"qualified_qty","type":"INT","comment":"合格数量"},{"name":"defect_qty","type":"INT","comment":"不良数量"}]'),
('quality_inspections', '质量检验表: 检验批次级的检验数量与缺陷类型分布, 用于缺陷构成与质量波动分析', '[{"name":"id","type":"BIGINT","comment":"主键, 自增"},{"name":"inspection_time","type":"DATETIME","comment":"检验时间"},{"name":"product_id","type":"VARCHAR(20)","comment":"产品编号"},{"name":"product_name","type":"VARCHAR(50)","comment":"产品名称"},{"name":"production_line","type":"VARCHAR(20)","comment":"产线编号(L1/L2/L3)"},{"name":"process_name","type":"VARCHAR(30)","comment":"工序名(注塑/焊接/装配/喷涂/包装)"},{"name":"inspection_qty","type":"INT","comment":"检验数量"},{"name":"qualified_qty","type":"INT","comment":"合格数量"},{"name":"defect_qty","type":"INT","comment":"不良数量"},{"name":"defect_type","type":"VARCHAR(30)","comment":"缺陷类型(划痕/气泡/尺寸偏差/色差/变形)"}]'),
('equipment_downtime', '设备停机表: 停机事件起止时间/时长/原因/报警次数, 用于设备效率与异常停机分析', '[{"name":"id","type":"BIGINT","comment":"主键, 自增"},{"name":"equipment_id","type":"VARCHAR(20)","comment":"设备编号"},{"name":"equipment_name","type":"VARCHAR(50)","comment":"设备名称"},{"name":"production_line","type":"VARCHAR(20)","comment":"产线编号(L1/L2/L3)"},{"name":"start_time","type":"DATETIME","comment":"停机开始时间"},{"name":"end_time","type":"DATETIME","comment":"停机结束时间"},{"name":"downtime_minutes","type":"INT","comment":"停机分钟数"},{"name":"reason","type":"VARCHAR(100)","comment":"停机原因(故障/换型/保养/待料)"},{"name":"alarm_count","type":"INT","comment":"报警次数"}]'),
('production_orders', '生产工单表: 每日下达工单的计划/完成数量与状态、计划与实际起止日期(未完成工单 actual_end 为 NULL)', '[{"name":"id","type":"BIGINT","comment":"主键, 自增"},{"name":"order_no","type":"VARCHAR(30)","comment":"工单编号(WO-日期-序号, 全表唯一)"},{"name":"product_id","type":"VARCHAR(20)","comment":"产品编号"},{"name":"product_name","type":"VARCHAR(50)","comment":"产品名称"},{"name":"production_line","type":"VARCHAR(20)","comment":"产线编号(L1/L2/L3)"},{"name":"planned_qty","type":"INT","comment":"计划数量"},{"name":"completed_qty","type":"INT","comment":"已完成数量(不超过计划数量)"},{"name":"status","type":"VARCHAR(10)","comment":"工单状态(已完成/进行中/已暂停)"},{"name":"planned_start","type":"DATE","comment":"计划开始日期(即工单下达日)"},{"name":"planned_end","type":"DATE","comment":"计划完成日期"},{"name":"actual_start","type":"DATE","comment":"实际开始日期(下达即开工, 等于计划开始日期)"},{"name":"actual_end","type":"DATE","comment":"实际完成日期(进行中/已暂停为 NULL)"}]'),
('inventory_records', '库存日快照表: 仓库x产品的每日期末库存/入库/出库快照, 用于库存水平、周转与呆滞/安全库存分析', '[{"name":"id","type":"BIGINT","comment":"主键, 自增"},{"name":"record_date","type":"DATE","comment":"快照日期"},{"name":"warehouse","type":"VARCHAR(10)","comment":"仓库编号(WH-01..WH-06)"},{"name":"product_id","type":"VARCHAR(20)","comment":"产品编号"},{"name":"product_name","type":"VARCHAR(50)","comment":"产品名称"},{"name":"inventory_qty","type":"INT","comment":"期末库存数量(当日快照)"},{"name":"inbound_qty","type":"INT","comment":"当日入库数量"},{"name":"outbound_qty","type":"INT","comment":"当日出库数量"}]');
