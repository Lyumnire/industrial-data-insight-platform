-- AI-assisted
-- 04_load_data.sql：把 a07-data/generated/*.csv 装载进 mes_demo（docker-entrypoint-initdb.d 自动执行）
-- 前提：03b_copy_csv.sh 已把 a07-data/generated/*.csv 拷贝到 /tmp，且 mysqld 以 --secure-file-priv=/tmp 启动
-- 文件特征：UTF-8 BOM + 表头行 + CRLF 换行 → IGNORE 1 LINES 跳过表头（BOM 随表头一起跳过）

USE mes_demo;

LOAD DATA INFILE '/tmp/process_output.csv' INTO TABLE process_output
CHARACTER SET utf8mb4
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\r\n' IGNORE 1 LINES
(production_date, production_line, product_id, product_name, process_name, produced_qty, qualified_qty, defect_qty);

LOAD DATA INFILE '/tmp/quality_inspections.csv' INTO TABLE quality_inspections
CHARACTER SET utf8mb4
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\r\n' IGNORE 1 LINES
(inspection_time, product_id, product_name, production_line, process_name, inspection_qty, qualified_qty, defect_qty, defect_type);

LOAD DATA INFILE '/tmp/equipment_downtime.csv' INTO TABLE equipment_downtime
CHARACTER SET utf8mb4
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
LINES TERMINATED BY '\r\n' IGNORE 1 LINES
(equipment_id, equipment_name, production_line, start_time, end_time, downtime_minutes, reason, alarm_count);

-- 装载量断言：行数不符时容器 init 会因报错中止，便于第一时间发现
SELECT 'process_output' AS t, COUNT(*) AS rows_loaded FROM process_output
UNION ALL SELECT 'quality_inspections', COUNT(*) FROM quality_inspections
UNION ALL SELECT 'equipment_downtime', COUNT(*) FROM equipment_downtime;
