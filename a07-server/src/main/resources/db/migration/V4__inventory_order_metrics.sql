-- AI-assisted (T-018 Java 底座组 · 复核人: 待主控评审后填写)
-- ============================================================================
-- V4：T-015 变更申请落地——库存/工单 7 指标 + topic 关联 + 口径规则
-- 双兼容约束同 V2/V3：JSON 一律 TEXT 存字符串；无 ENGINE/CHARSET；无 MySQL 专属类型。
-- 幂等：INSERT 一律 WHERE NOT EXISTS(code)；UPDATE 仅在目标编码尚未出现时写入。
-- 口径来源: docs/tasks/T-015-数据底座补全.md 变更申请 + a07-data/sql/02_seed_knowledge.sql
--           + a07-data/corpus/corpus.json 的 METRICS（编码/formula_sql 与之对齐）。
-- 特别约束: 禁止修改已应用的 V2__knowledge.sql / V3__metadata.sql，本迁移只做增量。
-- ============================================================================

-- ---------- business_metrics +7（生产工单 2 + 库存 5），幂等 ----------

INSERT INTO business_metrics (code, name, description, formula_sql, unit, domain, source_tables, source_columns, status)
SELECT 'order_count', '工单数量',
       '统计周期内工单条数, 可按状态/产线/产品分组(已暂停占比=R-H 演示口径)',
       'COUNT(*)', '单', '生产',
       '["production_orders"]', '["production_orders.order_no"]', 'active'
WHERE NOT EXISTS (SELECT 1 FROM business_metrics WHERE code = 'order_count');

INSERT INTO business_metrics (code, name, description, formula_sql, unit, domain, source_tables, source_columns, status)
SELECT 'order_completion_rate', '工单完成率',
       '完成率=已完成数量/计划数量, 须先对 completed_qty 与 planned_qty 求和再相除, 禁止对行级完成率求平均',
       'SUM(completed_qty)/NULLIF(SUM(planned_qty),0)', '%', '生产',
       '["production_orders"]',
       '["production_orders.completed_qty","production_orders.planned_qty"]', 'active'
WHERE NOT EXISTS (SELECT 1 FROM business_metrics WHERE code = 'order_completion_rate');

INSERT INTO business_metrics (code, name, description, formula_sql, unit, domain, source_tables, source_columns, status)
SELECT 'inventory_qty', '期末库存',
       '库存日快照的期末库存数量; 按仓库/产品统计时取最新一日或周期均值',
       'SUM(inventory_qty)', '件', '库存',
       '["inventory_records"]', '["inventory_records.inventory_qty"]', 'active'
WHERE NOT EXISTS (SELECT 1 FROM business_metrics WHERE code = 'inventory_qty');

INSERT INTO business_metrics (code, name, description, formula_sql, unit, domain, source_tables, source_columns, status)
SELECT 'inbound_qty', '入库量',
       '统计周期内各仓库/产品的入库数量总和',
       'SUM(inbound_qty)', '件', '库存',
       '["inventory_records"]', '["inventory_records.inbound_qty"]', 'active'
WHERE NOT EXISTS (SELECT 1 FROM business_metrics WHERE code = 'inbound_qty');

INSERT INTO business_metrics (code, name, description, formula_sql, unit, domain, source_tables, source_columns, status)
SELECT 'outbound_qty', '出库量',
       '统计周期内各仓库/产品的出库数量总和',
       'SUM(outbound_qty)', '件', '库存',
       '["inventory_records"]', '["inventory_records.outbound_qty"]', 'active'
WHERE NOT EXISTS (SELECT 1 FROM business_metrics WHERE code = 'outbound_qty');

INSERT INTO business_metrics (code, name, description, formula_sql, unit, domain, source_tables, source_columns, status)
SELECT 'inventory_turnover', '库存周转次数',
       '近似口径=周期出库总量/日均库存, 日均库存以 AVG(inventory_qty) 近似',
       'SUM(outbound_qty)/NULLIF(AVG(inventory_qty),0)', '次', '库存',
       '["inventory_records"]',
       '["inventory_records.outbound_qty","inventory_records.inventory_qty"]', 'active'
WHERE NOT EXISTS (SELECT 1 FROM business_metrics WHERE code = 'inventory_turnover');

INSERT INTO business_metrics (code, name, description, formula_sql, unit, domain, source_tables, source_columns, status)
SELECT 'safety_stock_line', '安全库存预警线',
       '样例库约定: 安全库存=该产品日均出库量x7; 期末库存低于该线视为缺货风险(如 P-1001 近14天)',
       'AVG(outbound_qty)*7', '件', '库存',
       '["inventory_records"]',
       '["inventory_records.outbound_qty","inventory_records.inventory_qty"]', 'active'
WHERE NOT EXISTS (SELECT 1 FROM business_metrics WHERE code = 'safety_stock_line');

-- ---------- analysis_topics.related_metric_ids 幂等更新 ----------
-- topic_inventory: V2 种子为 '[]'，补库存 5 指标。
-- topic_production: V2 仅 output_qty，追加工单 2 指标（保留已有 output_qty）。
-- 两处均在目标编码已出现时跳过，避免覆盖人工调整、保证重复执行安全。

UPDATE analysis_topics
SET related_metric_ids = '["inventory_qty","inbound_qty","outbound_qty","inventory_turnover","safety_stock_line"]',
    updated_at         = CURRENT_TIMESTAMP
WHERE code = 'topic_inventory'
  AND (related_metric_ids IS NULL
       OR related_metric_ids = ''
       OR related_metric_ids = '[]'
       OR related_metric_ids NOT LIKE '%inventory_qty%');

UPDATE analysis_topics
SET related_metric_ids = '["output_qty","order_count","order_completion_rate"]',
    updated_at         = CURRENT_TIMESTAMP
WHERE code = 'topic_production'
  AND (related_metric_ids IS NULL
       OR related_metric_ids = ''
       OR related_metric_ids NOT LIKE '%order_count%');

-- ---------- business_rules +3（T-015 建议口径规则），幂等 ----------

INSERT INTO business_rules (code, name, rule_type, content, applies_to, status)
SELECT 'rule_order_inventory_sum_before_divide', '完成率/周转口径：先聚合再相除', '口径',
       '工单完成率、库存周转次数等比率指标必须先按维度对分子分母分别聚合再相除（如 SUM(completed_qty)/NULLIF(SUM(planned_qty),0)、SUM(outbound_qty)/NULLIF(AVG(inventory_qty),0)），禁止对行级比率求平均，否则结果失真。',
       '["order_completion_rate","inventory_turnover"]', 'active'
WHERE NOT EXISTS (SELECT 1 FROM business_rules WHERE code = 'rule_order_inventory_sum_before_divide');

INSERT INTO business_rules (code, name, rule_type, content, applies_to, status)
SELECT 'rule_safety_stock_daily_outbound_x7', '安全库存口径：日均出库×7', '口径',
       '安全库存预警线=该产品日均出库量×7（AVG(outbound_qty)*7）；期末库存低于该线视为缺货风险。样例库已注入相关业务规律（如 P-1001 近14天跌破安全线）。',
       '["safety_stock_line","outbound_qty","inventory_qty"]', 'active'
WHERE NOT EXISTS (SELECT 1 FROM business_rules WHERE code = 'rule_safety_stock_daily_outbound_x7');

INSERT INTO business_rules (code, name, rule_type, content, applies_to, status)
SELECT 'rule_time_anchor_max_date', '时间锚点：最近N天以 MAX(日期列) 为基准', '时间',
       '库存/工单类问题中的"最近N天"一律以业务表日期列的 MAX 值为锚点（inventory_records.record_date、production_orders.planned_start），而非当前系统时间；含锚点当天，时区 Asia/Shanghai。',
       '["inventory_qty","inbound_qty","outbound_qty","inventory_turnover","safety_stock_line","order_count","order_completion_rate"]', 'active'
WHERE NOT EXISTS (SELECT 1 FROM business_rules WHERE code = 'rule_time_anchor_max_date');
