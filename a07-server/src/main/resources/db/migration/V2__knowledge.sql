-- AI-assisted (T-016 Java 底座增强 S2/S4 · 复核人: 待主控评审后填写)
-- ============================================================================
-- V2：业务知识四实体表 + 种子（语义自 a07-data/sql/02_seed_knowledge.sql 移植）
--     + S4 会话/任务持久化五表（工单允许并入 V2 或 V3，取 V2）。
-- 双兼容约束：同一脚本在 H2(MODE=MySQL) 与 MySQL 8 上执行——
--   * 不用 MySQL 专属类型（JSON/MEDIUMTEXT），JSON 一律 TEXT 存字符串；
--   * 不用表级 ENGINE/CHARSET 子句；唯一键统一 CONSTRAINT ... UNIQUE 语法。
-- 指标种子与 a07-data/corpus/build_corpus.py 的 METRICS 静态对账（改任一侧须同步）。
-- ============================================================================

-- ---------- S2 四实体 ----------

-- 业务对象：业务域内的分析主体（产品/工单/产线/工序/设备/质量检验/缺陷/库存）
CREATE TABLE business_objects (
    id          BIGINT        NOT NULL AUTO_INCREMENT,
    code        VARCHAR(50)   NOT NULL COMMENT '对象编码(英文, 唯一)',
    name        VARCHAR(100)  NOT NULL COMMENT '对象名称(中文)',
    description VARCHAR(500)  NOT NULL COMMENT '对象业务含义',
    domain      VARCHAR(20)   NOT NULL COMMENT '业务域(生产/质量/设备/库存)',
    status      VARCHAR(20)   NOT NULL DEFAULT 'active' COMMENT '状态(active/disabled)',
    created_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT uk_business_objects_code UNIQUE (code)
);

-- 业务指标：口径以可展开的 SQL 片段沉淀（NL2SQL 优先引用）
CREATE TABLE business_metrics (
    id             BIGINT        NOT NULL AUTO_INCREMENT,
    code           VARCHAR(50)   NOT NULL COMMENT '指标编码(英文, 唯一)',
    name           VARCHAR(100)  NOT NULL COMMENT '指标名称(中文)',
    description    VARCHAR(500)  NOT NULL COMMENT '指标业务含义与口径说明',
    formula_sql    VARCHAR(500)  NOT NULL COMMENT '计算公式(SQL 片段)',
    unit           VARCHAR(20)   NOT NULL COMMENT '计量单位',
    domain         VARCHAR(20)   NOT NULL COMMENT '业务域(生产/质量/设备/库存)',
    source_tables  TEXT          NOT NULL COMMENT '来源表(JSON 数组字符串, 如 ["process_output"])',
    source_columns TEXT          NOT NULL COMMENT '来源字段(JSON 数组字符串, 如 ["process_output.qualified_qty"])',
    status         VARCHAR(20)   NOT NULL DEFAULT 'active' COMMENT '状态(active/disabled)',
    created_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT uk_business_metrics_code UNIQUE (code)
);

-- 业务规则：口径/时间/空值/异常/特殊 五类，applies_to 指向指标编码
CREATE TABLE business_rules (
    id          BIGINT        NOT NULL AUTO_INCREMENT,
    code        VARCHAR(50)   NOT NULL COMMENT '规则编码(英文, 唯一)',
    name        VARCHAR(100)  NOT NULL COMMENT '规则名称(中文)',
    rule_type   VARCHAR(20)   NOT NULL COMMENT '规则类型(口径/时间/空值/异常/特殊)',
    content     TEXT          NOT NULL COMMENT '规则内容(自然语言, 供提示词注入)',
    applies_to  TEXT          NOT NULL COMMENT '适用指标编码(JSON 数组字符串, 空数组表示全局)',
    status      VARCHAR(20)   NOT NULL DEFAULT 'active' COMMENT '状态(active/disabled)',
    created_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT uk_business_rules_code UNIQUE (code)
);

-- 分析主题：面向主题导览与知识图谱，关联对象/指标（存业务编码, 跨环境稳定）
CREATE TABLE analysis_topics (
    id                 BIGINT        NOT NULL AUTO_INCREMENT,
    code               VARCHAR(50)   NOT NULL COMMENT '主题编码(英文, 唯一)',
    name               VARCHAR(100)  NOT NULL COMMENT '主题名称(中文)',
    description        VARCHAR(500)  NOT NULL COMMENT '主题说明',
    domain             VARCHAR(20)   NOT NULL COMMENT '业务域(生产/质量/设备/库存)',
    related_object_ids TEXT          NOT NULL COMMENT '关联业务对象编码(JSON 数组字符串)',
    related_metric_ids TEXT          NOT NULL COMMENT '关联业务指标编码(JSON 数组字符串)',
    status             VARCHAR(20)   NOT NULL DEFAULT 'active' COMMENT '状态(active/disabled)',
    created_at         DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT uk_analysis_topics_code UNIQUE (code)
);

-- ---------- 种子：业务对象 8 个 ----------
INSERT INTO business_objects (code, name, description, domain, status) VALUES
('product',            '产品',     '产品主数据：产出与检验记录均归属到产品维度', '生产', 'active'),
('work_order',         '生产工单', '生产工单的执行与完工情况，产量可按工单归集', '生产', 'active'),
('production_line',    '产线',     '产线(L1/L2/L3)的产能与效率分析主体', '生产', 'active'),
('process',            '工序',     '注塑/焊接/装配/喷涂/包装五大工序的产出与质量', '生产', 'active'),
('equipment',          '设备',     '设备运行状态、停机事件与报警的分析主体', '设备', 'active'),
('quality_inspection', '质量检验', '检验批次级的检验数量与合格情况', '质量', 'active'),
('defect',             '缺陷',     '缺陷类型(划痕/气泡/尺寸偏差/色差/变形)分布与构成', '质量', 'active'),
('inventory',          '库存',     '原料/成品库存水平与周转效率', '库存', 'active');

-- ---------- 种子：业务指标 6 条（自 02_seed_knowledge.sql 的 v_metric 移植） ----------
INSERT INTO business_metrics (code, name, description, formula_sql, unit, domain, source_tables, source_columns, status) VALUES
('output_qty', '产量', '统计周期内各产线/工序/产品的投产数量总和', 'SUM(produced_qty)', '件', '生产', '["process_output"]', '["process_output.produced_qty"]', 'active'),
('qualified_qty', '合格数', '统计周期内合格数量总和', 'SUM(qualified_qty)', '件', '质量', '["process_output"]', '["process_output.qualified_qty"]', 'active'),
('defect_qty', '不良数', '统计周期内不良数量总和', 'SUM(defect_qty)', '件', '质量', '["process_output"]', '["process_output.defect_qty"]', 'active'),
('process_yield_rate', '工序良率', '良率=合格数/投产数, 须先按维度求和再相除, 禁止对行级比率求平均', 'SUM(qualified_qty)/NULLIF(SUM(produced_qty),0)', '%', '质量', '["process_output"]', '["process_output.qualified_qty","process_output.produced_qty"]', 'active'),
('defect_rate', '不良率', '不良率=不良数/投产数, 与良率互补, 同样先求和再相除', 'SUM(defect_qty)/NULLIF(SUM(produced_qty),0)', '%', '质量', '["process_output"]', '["process_output.defect_qty","process_output.produced_qty"]', 'active'),
('downtime_minutes', '停机时长', '统计周期内设备停机分钟数总和, 可按设备/产线/原因分组', 'SUM(downtime_minutes)', '分钟', '设备', '["equipment_downtime"]', '["equipment_downtime.downtime_minutes"]', 'active');

-- ---------- 种子：业务规则 4 条 ----------
INSERT INTO business_rules (code, name, rule_type, content, applies_to, status) VALUES
('rule_yield_sum_before_divide', '良率口径：先求和再相除', '口径',
 '工序良率/不良率等比率指标必须先按维度对分子分母分别求和再相除（SUM(qualified_qty)/NULLIF(SUM(produced_qty),0)），禁止对行级比率求平均，否则结果失真。',
 '["process_yield_rate","defect_rate"]', 'active'),
('rule_time_range_default', '时间范围解释', '时间',
 '用户问题中的"最近N天/本月/本周"默认按数据时间列解释：产量/检验用 production_date/inspection_time，停机用 start_time；"最近N天"含当天，时区为 Asia/Shanghai。',
 '[]', 'active'),
('rule_null_handling', '空值处理', '空值',
 'quality_inspections.defect_type 为空表示该批次无不良，统计缺陷构成时排除空值而非计为未知缺陷；equipment_downtime.reason 为空的事件计入停机时长汇总但不参与停机原因分类。',
 '["defect_qty","downtime_minutes"]', 'active'),
('rule_downtime_aggregation', '停机汇总口径', '口径',
 '停机时长按停机事件整段汇总（跨日事件整体归入开始日期），禁止按天切分重复计时；如需计算停机率，分母为 设备数×统计期自然分钟数。',
 '["downtime_minutes"]', 'active');

-- ---------- 种子：分析主题 4 个 ----------
INSERT INTO analysis_topics (code, name, description, domain, related_object_ids, related_metric_ids, status) VALUES
('topic_production', '生产分析', '产量趋势、产线/工序/工单维度的产出对比与达成分析', '生产', '["process","production_line","work_order","product"]', '["output_qty"]', 'active'),
('topic_quality', '质量分析', '良率/不良率走势、缺陷类型构成与质量波动归因', '质量', '["quality_inspection","defect","process"]', '["process_yield_rate","defect_rate","qualified_qty","defect_qty"]', 'active'),
('topic_equipment', '设备分析', '设备停机时长、停机原因分布与异常停机识别', '设备', '["equipment"]', '["downtime_minutes"]', 'active'),
('topic_inventory', '库存分析', '库存水平、周转效率与呆滞风险', '库存', '["inventory"]', '[]', 'active');

-- ---------- S4 会话/任务持久化五表（工单 S4，并入本迁移）----------

-- 会话表：session_id 为引擎侧会话 UUID（chat/analyze 透传时的标识）
CREATE TABLE chat_sessions (
    id         BIGINT        NOT NULL AUTO_INCREMENT,
    session_id VARCHAR(64)   NOT NULL COMMENT '引擎会话 UUID',
    title      VARCHAR(200)  NULL COMMENT '会话标题(通常取首个问题)',
    username   VARCHAR(50)   NULL COMMENT '归属用户(会话 CRUD 落地时写入; 归档回调无法归属时为空)',
    created_at DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT uk_chat_sessions_session UNIQUE (session_id)
);

-- 消息表：role = user|assistant|system
CREATE TABLE chat_messages (
    id         BIGINT        NOT NULL AUTO_INCREMENT,
    session_id VARCHAR(64)   NOT NULL COMMENT '所属会话 UUID',
    role       VARCHAR(20)   NOT NULL COMMENT '角色(user/assistant/system)',
    content    TEXT          NULL COMMENT '消息内容',
    event_ref  VARCHAR(64)   NULL COMMENT '关联事件/任务引用(如 task id)',
    created_at DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);

-- 分析任务主表：plan_json 为 AnalysisPlan 标准对象
CREATE TABLE analysis_tasks (
    id          BIGINT        NOT NULL AUTO_INCREMENT,
    session_id  VARCHAR(64)   NOT NULL COMMENT '引擎会话 UUID',
    question    VARCHAR(500)  NOT NULL COMMENT '用户问题',
    plan_json   TEXT          NULL COMMENT 'AnalysisPlan JSON(右侧分析档案)',
    status      VARCHAR(20)   NOT NULL DEFAULT 'completed' COMMENT '状态(completed/failed)',
    result_ref  VARCHAR(64)   NULL COMMENT '结果引用(analysis_results.id)',
    created_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    duration_ms BIGINT        NULL COMMENT '总耗时(毫秒, 引擎 done 帧 durationMs)',
    tokens_cost BIGINT        NULL COMMENT 'token 消耗(引擎 done 帧 tokensCost)',
    PRIMARY KEY (id)
);

-- 分析步骤表：引擎 step 事件的时间线存档
CREATE TABLE analysis_steps (
    id          BIGINT        NOT NULL AUTO_INCREMENT,
    task_id     BIGINT        NOT NULL COMMENT '所属任务 id(analysis_tasks.id)',
    step_id     VARCHAR(64)   NOT NULL COMMENT '引擎步骤号(stepId)',
    name        VARCHAR(100)  NOT NULL COMMENT '步骤名(意图理解/知识检索/生成SQL/执行等)',
    detail      VARCHAR(500)  NULL COMMENT '步骤说明',
    started_at  DATETIME      NULL COMMENT '开始时间(引擎发帧时刻)',
    finished_at DATETIME      NULL COMMENT '结束时间(引擎发帧时刻)',
    PRIMARY KEY (id)
);

-- 分析结果表：标准分析结果对象(ADR-2) + Markdown 报告全文
CREATE TABLE analysis_results (
    id                   BIGINT       NOT NULL AUTO_INCREMENT,
    task_id              BIGINT       NOT NULL COMMENT '所属任务 id(analysis_tasks.id)',
    standard_result_json TEXT         NULL COMMENT '标准分析结果对象 JSON(docs/03 §4)',
    report_markdown      TEXT         NULL COMMENT 'Markdown 报告全文(report 事件)',
    created_at           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);
