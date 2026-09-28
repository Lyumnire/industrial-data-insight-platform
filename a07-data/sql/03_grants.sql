-- AI-assisted (T-002 数据底座 v1 · 数据评测组 · 复核人: 待主控评审后填写)
-- ============================================================================
-- 只读账号授权(红线 R1: Agent/LLM 的一切 SQL 只能经只读账号执行,
-- 严禁在 LLM 进程或提示词上下文中出现管理员凭据)
-- 规范来源: docs/04-多Agent协作与团队规范.md §5 R1; P1 计划 Task 4 Step 4.3
--
-- 执行顺序: 必须在 01_mes_demo_ddl.sql 之后执行(依赖 mes_demo 库存在)。
-- 红线 R3 注意: 下方口令仅为本地演示环境的默认值(不入任何正式环境),
--   生产/公网部署必须改为强口令并通过环境变量/配置中心注入, 不得明文提交。
-- 仅 GRANT SELECT, 不授予任何写权限; 权限面只有 mes_demo, 平台库 a07_platform 不开放。
-- ============================================================================

CREATE USER IF NOT EXISTS 'mes_readonly'@'%' IDENTIFIED BY 'MesRo@a07demo';
GRANT SELECT ON mes_demo.* TO 'mes_readonly'@'%';
FLUSH PRIVILEGES;
