# a07-data · 数据底座（T-002 v1 + T-015 补全）

数据评测组交付：mes_demo 业务样例库建库 SQL、合成数据生成器、指标口径种子、A3 检索语料。
规范来源：`docs/plans/2026-09-19-P1-走通骨架.md` §Task 2；工单：`docs/tasks/T-002`（已关闭）、`docs/tasks/T-015-数据底座补全.md`。

## 1. 目录结构

```
a07-data/
├── sql/
│   ├── 01_mes_demo_ddl.sql          # mes_demo 原三表 DDL：工序产量/质量检验/设备停机
│   ├── 02_seed_knowledge.sql        # a07_platform 最小表 v_metric/v_table_meta + 13 条指标口径种子（含工单/库存）
│   ├── 03_grants.sql                # 只读账号 mes_readonly（红线 R1：仅 GRANT SELECT ON mes_demo.*）
│   ├── 03b_copy_csv.sh              # 容器 initdb：把 generated/*.csv 拷到 /tmp（secure-file-priv）
│   ├── 04_load_data.sql             # 容器 initdb：LOAD 原三表 CSV
│   ├── 06_orders_inventory_ddl.sql  # T-015：production_orders + inventory_records DDL
│   └── 07_load_extra.sql            # T-015：幂等装载两表（TRUNCATE + LOAD DATA；顺序在 06 之后）
├── generate.py                      # 合成数据生成器（仅标准库，random.seed(42) 可复现）
├── corpus/
│   ├── build_corpus.py              # 生成 A3 检索语料 corpus.json（表/指标/示例三方静态对账）
│   └── corpus.json                  # （运行后生成）5 表 + 13 指标 + 12 示例
└── generated/                       # （运行后生成）五张表 CSV
    ├── process_output.csv           # 约 8.1 万行（90天 x 3产线 x 5工序 x 6产品 x 10批次）
    ├── quality_inspections.csv      # 约 2.0 万行
    ├── equipment_downtime.csv       # 约 1500 行
    ├── production_orders.csv        # 约 3000 行（90天 x 每天30-40单；actual_end 可为字面量 NULL）
    └── inventory_records.csv        # 3240 行（90天 x 6仓库 x 6产品 逐日快照）
```

## 2. 运行方式

Python 3.10+，仅标准库（random/csv/statistics/datetime/json），无第三方依赖：

```bash
python a07-data/generate.py              # 生成 5 个 CSV + 打印统计摘要 + 断言 R-A~R-H（失败退出码非 0）
python a07-data/corpus/build_corpus.py   # 生成 corpus.json（表/指标/示例 SQL 静态对账）
```

约束：新两表的随机消耗**排在原三表之后**，保证 P1 三张 CSV 在 seed=42 下逐字节可复现。

## 3. SQL 执行与数据入库

`deploy/docker-compose.yml` 已把 `a07-data/sql/` 挂载为 MySQL `/docker-entrypoint-initdb.d`，
首次建容器按文件名序自动执行：

```
01_mes_demo_ddl.sql → 02_seed_knowledge.sql → 03_grants.sql → 03b_copy_csv.sh
→ 04_load_data.sql（原三表）→ 06_orders_inventory_ddl.sql（两表 DDL）→ 07_load_extra.sql（两表数据）
```

`03b_copy_csv.sh` 执行 `cp -f /var/lib/csv-src/*.csv /tmp/`，会一并拷贝 T-015 两张新 CSV，**无需改 03b**。
`07_load_extra.sql` 使用 `LOAD DATA INFILE '/tmp/...'`（与 04 同模式，依赖容器 `--secure-file-priv=/tmp`），
先 `TRUNCATE` 再装载，可重复执行；`actual_end` 字面量 `NULL` 经 `NULLIF(...,'NULL')` 转为 SQL NULL。

手动执行（容器外）：

```bash
mysql -uroot -p < a07-data/sql/01_mes_demo_ddl.sql
mysql -uroot -p < a07-data/sql/02_seed_knowledge.sql
mysql -uroot -p < a07-data/sql/03_grants.sql
mysql -uroot -p < a07-data/sql/06_orders_inventory_ddl.sql
# 将 generated/*.csv 放到 mysqld secure-file-priv 目录后：
mysql -uroot -p < a07-data/sql/04_load_data.sql
mysql -uroot -p < a07-data/sql/07_load_extra.sql
# 或不经 secure-file-priv，改用客户端 LOCAL（需 local_infile=1）：
# LOAD DATA LOCAL INFILE '<path>/production_orders.csv' INTO TABLE production_orders ...
```

已有数据的实例增量刷新：先跑 `generate.py`，再执行 `06`（幂等建表）+ `07`（TRUNCATE 重装两表）。

## 4. 注入的业务规律（演示/评测用，generate.py 自动断言）

| 规律 | 所在表 | 断言 |
|---|---|---|
| R-A L3 产量最后 30 天环比约 -15% | process_output | L3 末 30 天日均产量 < 前 60 天 |
| R-B "焊接"良率基线低约 5 个百分点 | process_output | 焊接良率 < 全体良率均值 |
| R-C "划痕"缺陷最后 21 天占比约翻倍 | quality_inspections | 末 21 天占比 > 之前占比 x 1.5 |
| R-D 设备 EQ-07（L2）5 次 >120 分钟长停机 | equipment_downtime | EQ-07 总停机时长全厂 top1 |
| R-E P-1003 库存近 60 天持续走高（呆滞） | inventory_records | 期末较 60 天前 > +30%（样例约 +80%） |
| R-F WH-02 每周五出库高峰 | inventory_records | 周五日均出库 > 其他日 x 1.6（样例约 2.4x） |
| R-G P-1001 近 14 天跌破安全库存线 | inventory_records | 近 14 天存在 inventory_qty < 日均出库 x 7 |
| R-H L2 最近 30 天"已暂停"工单占比显著偏高 | production_orders | L2 暂停占比 ≥8% 且 > 其他产线 x 2 |

## 5. corpus.json（A3 检索语料，P2 向量 collection 同构）

结构：`{tables:[{name, comment, description, ddl_m_schema, columns, relations}], metrics:[与 v_metric 一致的 8 字段], examples:[{question, q, sql}]}`。

- T-015 后：`tables=5`（含 production_orders / inventory_records）、`metrics=13`、`examples=12`。
- 「库存呆滞」「工单完成率」「安全库存」「库存周转」在指标层（`inventory_turnover` / `order_completion_rate` / `safety_stock_line` 等）与示例层均可检索。
- 示例 SQL 均为单条 SELECT，"最近 N 天"以 `MAX(日期列)` 为锚点，兼容 sqlguard。
- build_corpus.py 静态对账：表名/列名对齐 01+06 DDL；指标编码对齐 02_seed_knowledge.sql；示例标识符白名单校验（字符串字面量除外）。断言数量与 TABLES/METRICS/EXAMPLES 联动，不写死。

## 6. 红线与注意事项

- **R1**：Agent/LLM 的一切 SQL 只经只读账号 `mes_readonly` 执行（`03_grants.sql` 仅 `GRANT SELECT ON mes_demo.*`；新表通过 `mes_demo.*` 已覆盖，无需额外授权）。
- **R3**：`03_grants.sql` 中的口令仅为本地演示默认值，生产必须改由环境变量注入，不得明文提交。
- **R5**：语料示例中的业务结论以 SQL 聚合表达，不写死编造数字；样例数据全部合成（NFR7）。
- 重新生成需保持 `random.seed(42)` 与「新表随机消耗在原三表之后」以保证可复现。
- **平台库同步（变更申请，见 T-015）**：`a07-server` V2 `business_metrics` 仍为 P1 六条指标，`topic_inventory.related_metric_ids` 为空；建议主控/Java 组按 `02_seed_knowledge.sql` 新增的 7 个编码（order_count / order_completion_rate / inventory_qty / inbound_qty / outbound_qty / inventory_turnover / safety_stock_line）同步平台库种子。
