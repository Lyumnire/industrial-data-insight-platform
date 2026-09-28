-- AI-assisted (T-022 Java 底座组 · 复核人: 待主控评审后填写)
-- ============================================================================
-- V5：BUG-016 修复——a07_platform.v_table_meta 补并 production_orders + inventory_records
-- 背景: v_table_meta 由 a07-data/sql/02_seed_knowledge.sql 预建（P1 种子，非 Flyway 管理），
--       T-015 虽已在种子脚本中补写两表元数据，但运行库未重新初始化，Flyway 也无对应迁移。
-- 双兼容约束同 V2–V4：JSON 用 TEXT；不用 ENGINE/CHARSET；唯一键用 CONSTRAINT ... UNIQUE。
-- 幂等：CREATE TABLE IF NOT EXISTS + INSERT ... WHERE NOT EXISTS(table_name)。
-- 元数据来源: a07-data/sql/02_seed_knowledge.sql（columns_json 与 01/06 DDL 列注释一致）。
-- 特别约束: 禁止修改已应用的 V1–V4，本迁移只做增量。
-- ============================================================================

-- ---------- 确保 v_table_meta 表存在（H2 测试库无预建种子，MySQL 生产库已存在则跳过） ----------
CREATE TABLE IF NOT EXISTS v_table_meta (
    id            BIGINT        NOT NULL AUTO_INCREMENT,
    table_name    VARCHAR(64)   NOT NULL COMMENT '业务库表名',
    description   VARCHAR(200)  NOT NULL COMMENT '表业务含义',
    columns_json  TEXT          NOT NULL COMMENT '列元数据 JSON 数组, 元素结构 {name,type,comment}',
    PRIMARY KEY (id),
    CONSTRAINT uk_v_table_meta_table UNIQUE (table_name)
);

-- ---------- 幂等并入 production_orders 表元数据 ----------
INSERT INTO v_table_meta (table_name, description, columns_json)
SELECT 'production_orders',
       '生产工单表: 每日下达工单的计划/完成数量与状态、计划与实际起止日期(未完成工单 actual_end 为 NULL)',
       '[{"name":"id","type":"BIGINT","comment":"主键, 自增"},{"name":"order_no","type":"VARCHAR(30)","comment":"工单编号(WO-日期-序号, 全表唯一)"},{"name":"product_id","type":"VARCHAR(20)","comment":"产品编号"},{"name":"product_name","type":"VARCHAR(50)","comment":"产品名称"},{"name":"production_line","type":"VARCHAR(20)","comment":"产线编号(L1/L2/L3)"},{"name":"planned_qty","type":"INT","comment":"计划数量"},{"name":"completed_qty","type":"INT","comment":"已完成数量(不超过计划数量)"},{"name":"status","type":"VARCHAR(10)","comment":"工单状态(已完成/进行中/已暂停)"},{"name":"planned_start","type":"DATE","comment":"计划开始日期(即工单下达日)"},{"name":"planned_end","type":"DATE","comment":"计划完成日期"},{"name":"actual_start","type":"DATE","comment":"实际开始日期(下达即开工, 等于计划开始日期)"},{"name":"actual_end","type":"DATE","comment":"实际完成日期(进行中/已暂停为 NULL)"}]'
WHERE NOT EXISTS (SELECT 1 FROM v_table_meta WHERE table_name = 'production_orders');

-- ---------- 幂等并入 inventory_records 表元数据 ----------
INSERT INTO v_table_meta (table_name, description, columns_json)
SELECT 'inventory_records',
       '库存日快照表: 仓库x产品的每日期末库存/入库/出库快照, 用于库存水平、周转与呆滞/安全库存分析',
       '[{"name":"id","type":"BIGINT","comment":"主键, 自增"},{"name":"record_date","type":"DATE","comment":"快照日期"},{"name":"warehouse","type":"VARCHAR(10)","comment":"仓库编号(WH-01..WH-06)"},{"name":"product_id","type":"VARCHAR(20)","comment":"产品编号"},{"name":"product_name","type":"VARCHAR(50)","comment":"产品名称"},{"name":"inventory_qty","type":"INT","comment":"期末库存数量(当日快照)"},{"name":"inbound_qty","type":"INT","comment":"当日入库数量"},{"name":"outbound_qty","type":"INT","comment":"当日出库数量"}]'
WHERE NOT EXISTS (SELECT 1 FROM v_table_meta WHERE table_name = 'inventory_records');
