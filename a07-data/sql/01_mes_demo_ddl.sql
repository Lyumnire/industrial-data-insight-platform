-- AI-assisted (T-002 数据底座 v1 · 数据评测组 · 复核人: 待主控评审后填写)
-- ============================================================================
-- mes_demo 业务样例库 P1 三表 DDL
-- 规范来源: docs/plans/2026-09-19-P1-走通骨架.md §Task 2 Step 2.1
-- 执行顺序: 本文件 -> 02_seed_knowledge.sql -> 03_grants.sql
-- 说明:
--   * deploy/docker-compose.yml 已将本目录挂载为 MySQL /docker-entrypoint-initdb.d,
--     首次建容器时按文件名序自动执行; 手动执行: mysql -uroot -p < 01_mes_demo_ddl.sql
--   * 表/列名与 a07-data/generate.py 输出的 CSV、a07-data/corpus/build_corpus.py
--     的语料三方一致(静态自查通过); 实库导入验证延至 T-008(Docker 未启动)。
--   * 数据量(由 generate.py 生成): process_output 约 8.1 万行,
--     quality_inspections 约 2 万行, equipment_downtime 约 1500 行。
-- ============================================================================

CREATE DATABASE IF NOT EXISTS mes_demo DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE mes_demo;

-- 1) 工序产量表: 产线 x 工序 x 产品 x 批次 的每日投产/合格/不良数量
CREATE TABLE IF NOT EXISTS process_output (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  production_date DATE NOT NULL COMMENT '生产日期',
  production_line VARCHAR(20) NOT NULL COMMENT '产线编号(L1/L2/L3)',
  product_id VARCHAR(20) NOT NULL COMMENT '产品编号',
  product_name VARCHAR(50) NOT NULL COMMENT '产品名称',
  process_name VARCHAR(30) NOT NULL COMMENT '工序名(注塑/焊接/装配/喷涂/包装)',
  produced_qty INT NOT NULL COMMENT '投产数量',
  qualified_qty INT NOT NULL COMMENT '合格数量',
  defect_qty INT NOT NULL COMMENT '不良数量',
  KEY idx_date (production_date),
  KEY idx_line (production_line)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='工序产量表';

-- 2) 质量检验表: 检验批次级别的数量与缺陷类型(defect_type 为空表示该批次无不良)
CREATE TABLE IF NOT EXISTS quality_inspections (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  inspection_time DATETIME NOT NULL COMMENT '检验时间',
  product_id VARCHAR(20) NOT NULL COMMENT '产品编号',
  product_name VARCHAR(50) NOT NULL COMMENT '产品名称',
  production_line VARCHAR(20) NOT NULL COMMENT '产线编号(L1/L2/L3)',
  process_name VARCHAR(30) NOT NULL COMMENT '工序名(注塑/焊接/装配/喷涂/包装)',
  inspection_qty INT NOT NULL COMMENT '检验数量',
  qualified_qty INT NOT NULL COMMENT '合格数量',
  defect_qty INT NOT NULL COMMENT '不良数量',
  defect_type VARCHAR(30) DEFAULT NULL COMMENT '缺陷类型(划痕/气泡/尺寸偏差/色差/变形)',
  KEY idx_time (inspection_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='质量检验表';

-- 3) 设备停机表: 停机事件(起止时间/时长/原因/报警次数)
--    注: 相比计划 DDL 增补 idx_equipment/idx_line 两个普通索引(不改动任何字段),
--    服务于"最近30天停机时间最长的设备 top5"等按设备/产线过滤的演示查询。
CREATE TABLE IF NOT EXISTS equipment_downtime (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  equipment_id VARCHAR(20) NOT NULL COMMENT '设备编号',
  equipment_name VARCHAR(50) NOT NULL COMMENT '设备名称',
  production_line VARCHAR(20) NOT NULL COMMENT '产线编号(L1/L2/L3)',
  start_time DATETIME NOT NULL COMMENT '停机开始时间',
  end_time DATETIME NOT NULL COMMENT '停机结束时间',
  downtime_minutes INT NOT NULL COMMENT '停机分钟数',
  reason VARCHAR(100) DEFAULT NULL COMMENT '停机原因(故障/换型/保养/待料)',
  alarm_count INT DEFAULT 0 COMMENT '报警次数',
  KEY idx_start (start_time),
  KEY idx_equipment (equipment_id),
  KEY idx_line (production_line)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='设备停机表';
