-- AI-assisted (T-015 数据底座补全 · 数据评测组 · 复核人: 待主控评审后填写)
-- ============================================================================
-- mes_demo 增补两表数据装载(幂等): production_orders + inventory_records
-- 规范来源: docs/tasks/T-015-数据底座补全.md
--
-- 执行顺序(严格):
--   01_mes_demo_ddl.sql -> 02_seed_knowledge.sql -> 03_grants.sql
--   -> 03b_copy_csv.sh(容器 initdb, 把 a07-data/generated/*.csv 拷到 /tmp)
--   -> 04_load_data.sql(原三表) -> 06_orders_inventory_ddl.sql(两表 DDL) -> 本文件
--   deploy/docker-compose.yml 将 a07-data/sql 挂载为 /docker-entrypoint-initdb.d,
--   首次建容器按文件名序自动执行; 03b 的 `cp -f /var/lib/csv-src/*.csv /tmp/`
--   会一并拷贝 production_orders.csv / inventory_records.csv, 无需改 03b。
--
-- 幂等性: 先 TRUNCATE 再 LOAD, 重复执行结果一致(重建容器或手动刷新均可)。
--   若执行账号无 TRUNCATE 权限, 可将 TRUNCATE 换成 DELETE FROM(无 WHERE 全表删)。
--
-- CSV 约定(与 generate.py write_csv 一致):
--   UTF-8 BOM + 表头行 + CRLF; IGNORE 1 LINES 跳过表头(BOM 随表头跳过);
--   不含自增 id 列; production_orders.actual_end 未完成工单写字面量 NULL,
--   下方经 NULLIF(@actual_end,'NULL') 转为 SQL NULL。
--
-- 手动装载(容器外, 不经 03b):
--   1) 先执行 06 建表; 2) 把 generated/*.csv 放到 mysqld secure-file-priv 目录
--   (compose 配置为 /tmp)后执行本文件; 或改用客户端 LOCAL 语法:
--     LOAD DATA LOCAL INFILE '<path>/production_orders.csv' INTO TABLE production_orders ...
--   (需服务器 local_infile=1 且客户端允许 LOCAL)。
-- ============================================================================

USE mes_demo;

TRUNCATE TABLE production_orders;
TRUNCATE TABLE inventory_records;

-- 生产工单表(约 3000 行); actual_end 字面量 NULL -> SQL NULL
LOAD DATA INFILE '/tmp/production_orders.csv' INTO TABLE production_orders
CHARACTER SET utf8mb4
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\r\n' IGNORE 1 LINES
(order_no, product_id, product_name, production_line, planned_qty, completed_qty,
 status, planned_start, planned_end, actual_start, @actual_end)
SET actual_end = NULLIF(@actual_end, 'NULL');

-- 库存日快照表(固定 3240 行 = 90天 x 6仓库 x 6产品)
LOAD DATA INFILE '/tmp/inventory_records.csv' INTO TABLE inventory_records
CHARACTER SET utf8mb4
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\r\n' IGNORE 1 LINES
(record_date, warehouse, product_id, product_name, inventory_qty, inbound_qty, outbound_qty);

-- 装载量核对: 行数异常时便于第一时间发现(initdb 阶段仅打印, 不强制中止)
SELECT 'production_orders' AS t, COUNT(*) AS rows_loaded FROM production_orders
UNION ALL SELECT 'inventory_records', COUNT(*) FROM inventory_records;
