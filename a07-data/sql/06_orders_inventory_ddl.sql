-- AI-assisted (T-015 数据底座补全 · 数据评测组 · 复核人: 待主控评审后填写)
-- ============================================================================
-- mes_demo 业务样例库 P2 增补两表 DDL: 生产工单表 + 库存日快照表
-- 规范来源: docs/tasks/T-015-数据底座补全.md; 赛题原文 §6 点名的 5 类业务表
--   (生产工单/工序产量/质量检验/设备停机/库存), P1 已建 3 张, 本文件补齐其余 2 张。
-- 执行顺序: 04_load_data.sql 之后执行; 与 a07-data/generate.py 输出的 CSV、
--   a07-data/corpus/build_corpus.py 的语料三方一致(该脚本末尾做静态对账)。
-- 幂等性: CREATE TABLE IF NOT EXISTS, 重复执行不重建; 数据幂等由 07_load_extra.sql
--   负责(TRUNCATE 后重装)。若日后调整列结构, 需先 DROP TABLE 再执行本文件。
-- 数据量(由 generate.py 生成): production_orders 约 3000 行(近90天, 每天30-40单),
--   inventory_records 3240 行(90天 x 6仓库 x 6产品 逐日快照)。
-- ============================================================================

CREATE DATABASE IF NOT EXISTS mes_demo DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE mes_demo;

-- 4) 生产工单表: 每日下达的生产工单(计划/完成数量与状态、计划与实际起止日期)
--    指标口径: 工单完成率 = SUM(completed_qty)/SUM(planned_qty)(先求和再相除)
CREATE TABLE IF NOT EXISTS production_orders (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  order_no VARCHAR(30) NOT NULL COMMENT '工单编号(WO-日期-序号, 全表唯一)',
  product_id VARCHAR(20) NOT NULL COMMENT '产品编号',
  product_name VARCHAR(50) NOT NULL COMMENT '产品名称',
  production_line VARCHAR(20) NOT NULL COMMENT '产线编号(L1/L2/L3)',
  planned_qty INT NOT NULL COMMENT '计划数量',
  completed_qty INT NOT NULL COMMENT '已完成数量(不超过计划数量)',
  status VARCHAR(10) NOT NULL COMMENT '工单状态(已完成/进行中/已暂停)',
  planned_start DATE NOT NULL COMMENT '计划开始日期(即工单下达日)',
  planned_end DATE NOT NULL COMMENT '计划完成日期',
  actual_start DATE NOT NULL COMMENT '实际开始日期(下达即开工, 等于计划开始日期)',
  actual_end DATE DEFAULT NULL COMMENT '实际完成日期(进行中/已暂停为 NULL)',
  UNIQUE KEY uk_order_no (order_no),
  KEY idx_planned_start (planned_start),
  KEY idx_status (status),
  KEY idx_line (production_line),
  KEY idx_product (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='生产工单表';

-- 5) 库存日快照表: 仓库 x 产品 的每日库存/入库/出库快照(期末库存 = 昨日库存 + 入库 - 出库)
--    指标口径: 库存周转近似 = SUM(outbound_qty)/AVG(inventory_qty)(周期出库总量/日均库存);
--    安全库存预警线 = 日均出库量 x 7(如 P-1001 近14天跌破); 呆滞预警 = 库存持续走高
--    而出货稀少(如 P-1003 近60天期末较期初 +80%)
CREATE TABLE IF NOT EXISTS inventory_records (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  record_date DATE NOT NULL COMMENT '快照日期',
  warehouse VARCHAR(10) NOT NULL COMMENT '仓库编号(WH-01..WH-06)',
  product_id VARCHAR(20) NOT NULL COMMENT '产品编号',
  product_name VARCHAR(50) NOT NULL COMMENT '产品名称',
  inventory_qty INT NOT NULL COMMENT '期末库存数量(当日快照)',
  inbound_qty INT NOT NULL COMMENT '当日入库数量',
  outbound_qty INT NOT NULL COMMENT '当日出库数量',
  KEY idx_record_date (record_date),
  KEY idx_warehouse (warehouse),
  KEY idx_product (product_id),
  KEY idx_wh_date (warehouse, record_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='库存日快照表';
