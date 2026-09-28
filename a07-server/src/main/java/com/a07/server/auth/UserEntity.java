// AI-assisted
package com.a07.server.auth;

import java.time.LocalDateTime;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

/**
 * sys_user 表实体（V1__init.sql 基线）。
 * 红线 R3：密码只存 BCrypt 哈希，任何链路不得写入/回传明文。
 */
@TableName("sys_user")
public class UserEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String username;

    /** BCrypt 哈希（$2a$...），禁止存明文 */
    private String passwordHash;

    /** 角色：admin | dm | user */
    private String role;

    private LocalDateTime createdAt;

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getUsername() {
        return username;
    }

    public void setUsername(String username) {
        this.username = username;
    }

    public String getPasswordHash() {
        return passwordHash;
    }

    public void setPasswordHash(String passwordHash) {
        this.passwordHash = passwordHash;
    }

    public String getRole() {
        return role;
    }

    public void setRole(String role) {
        this.role = role;
    }

    public LocalDateTime getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(LocalDateTime createdAt) {
        this.createdAt = createdAt;
    }
}
