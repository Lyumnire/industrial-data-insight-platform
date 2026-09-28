-- AI-assisted
-- T-006 平台库基线（P1 计划 §Task 6 Step 6.2）
-- 生产目标库：a07_platform（MySQL 8）；单测在 H2 MODE=MySQL 下执行同一脚本（工单验收口径）。
-- 红线 R3：密码只存 BCrypt 哈希，禁止明文入库。
-- 种子口令（P1 演示用，P2 收口轮换）：admin/admin123 · dm/dm123456 · user/user123456

CREATE TABLE sys_user (
    id            BIGINT        NOT NULL AUTO_INCREMENT,
    username      VARCHAR(50)   NOT NULL,
    password_hash VARCHAR(100)  NOT NULL COMMENT 'BCrypt 哈希($2a$...)',
    role          VARCHAR(20)   NOT NULL COMMENT 'admin|dm|user（管理员/数据管理员/业务用户）',
    created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT uk_sys_user_username UNIQUE (username)
);

INSERT INTO sys_user (username, password_hash, role) VALUES
    ('admin', '$2a$10$Jxd.trE4bCAstGlEaPA2TOm/TmAg2lbY0mpgiEkXv28p4i7pGd9SG', 'admin'),
    ('dm',    '$2a$10$k8TqASASNwzY1gBeh9j.HehDPErJ4i3f0pxsT8gzMJimO3iCnUvPS', 'dm'),
    ('user',  '$2a$10$9B2D4BeVCGkq.0U9xHUP7.j1WZBnKWu8bmMRbxsf2CNwQiIyhG5dC', 'user');
