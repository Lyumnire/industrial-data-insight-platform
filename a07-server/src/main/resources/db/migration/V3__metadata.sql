-- AI-assisted (T-016 Java 底座增强 S3 · 复核人: 待主控评审后填写)
-- ============================================================================
-- V3：元数据管理四表（docs/03 §3.4 "元数据七表"中本工单落地的四表）。
-- 双兼容约束同 V2：JSON 用 TEXT；不用 MySQL 专属子句。
-- 红线 R3：数据源密码不存明文——password_enc 存 AES-GCM 密文（DataSourceCipher）。
-- ============================================================================

-- 数据源注册：refresh 时按 jdbc_url/username/密码解密后建立只读连接采集
CREATE TABLE data_sources (
    id           BIGINT        NOT NULL AUTO_INCREMENT,
    name         VARCHAR(100)  NOT NULL COMMENT '数据源名称',
    db_type      VARCHAR(20)   NOT NULL COMMENT '数据库类型(mysql/h2)',
    jdbc_url     VARCHAR(500)  NOT NULL COMMENT 'JDBC 连接串',
    username     VARCHAR(100)  NULL COMMENT '连接用户名',
    password_enc VARCHAR(500)  NULL COMMENT '连接密码密文(AES-GCM, 红线 R3 禁明文)',
    status       VARCHAR(20)   NOT NULL DEFAULT 'active' COMMENT '状态(active/disabled)',
    description  VARCHAR(500)  NULL COMMENT '数据源说明',
    created_at   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);

-- 表级元数据：refresh 覆盖写（先删该数据源旧记录再插入）
CREATE TABLE table_metadata (
    id             BIGINT       NOT NULL AUTO_INCREMENT,
    data_source_id BIGINT       NOT NULL COMMENT '所属数据源 id(data_sources.id)',
    table_name     VARCHAR(64)  NOT NULL COMMENT '表名',
    table_comment  VARCHAR(500) NULL COMMENT '表注释',
    table_type     VARCHAR(30)  NOT NULL DEFAULT 'BASE TABLE' COMMENT '表类型(BASE TABLE/VIEW)',
    row_count      BIGINT       NULL COMMENT '采集时 COUNT(*) 行数',
    collected_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '采集时间',
    PRIMARY KEY (id)
);

-- 列级元数据：含主键标记与样例值(JSON 数组, 每列 ≤5 个 DISTINCT 截断)
CREATE TABLE column_metadata (
    id             BIGINT       NOT NULL AUTO_INCREMENT,
    data_source_id BIGINT       NOT NULL COMMENT '所属数据源 id(data_sources.id)',
    table_name     VARCHAR(64)  NOT NULL COMMENT '所属表名',
    column_name    VARCHAR(64)  NOT NULL COMMENT '列名',
    ordinal        INT          NOT NULL DEFAULT 0 COMMENT '列序号(从 1 起)',
    data_type      VARCHAR(100) NOT NULL COMMENT '数据类型(如 VARCHAR(50)/BIGINT)',
    nullable       VARCHAR(5)   NOT NULL DEFAULT 'YES' COMMENT '是否可空(YES/NO)',
    primary_key    VARCHAR(5)   NOT NULL DEFAULT 'NO' COMMENT '是否主键(YES/NO)',
    column_comment VARCHAR(500) NULL COMMENT '列注释',
    sample_values  TEXT         NULL COMMENT '样例值(JSON 数组字符串, ≤5 个)',
    PRIMARY KEY (id)
);

-- 表间关系：外键采集（getImportedKeys）+ 人工标注预留
CREATE TABLE table_relationships (
    id              BIGINT       NOT NULL AUTO_INCREMENT,
    data_source_id  BIGINT       NOT NULL COMMENT '所属数据源 id(data_sources.id)',
    source_table    VARCHAR(64)  NOT NULL COMMENT '子表(含外键方)',
    source_column   VARCHAR(64)  NOT NULL COMMENT '子表外键列',
    target_table    VARCHAR(64)  NOT NULL COMMENT '父表(被引用方)',
    target_column   VARCHAR(64)  NOT NULL COMMENT '父表被引用列',
    relation_type   VARCHAR(20)  NOT NULL DEFAULT 'fk' COMMENT '关系来源(fk/manual)',
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);
