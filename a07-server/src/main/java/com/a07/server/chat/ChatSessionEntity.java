// AI-assisted
package com.a07.server.chat;

import java.time.LocalDateTime;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

/** chat_sessions 表实体（V2__knowledge.sql）。 */
@TableName("chat_sessions")
public class ChatSessionEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String sessionId;

    private String title;

    private String username;

    private LocalDateTime createdAt;

    /** 最近任务状态，非表列，查询时装配。 */
    @TableField(exist = false)
    private String lastTaskStatus;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getSessionId() { return sessionId; }
    public void setSessionId(String sessionId) { this.sessionId = sessionId; }
    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }
    public String getUsername() { return username; }
    public void setUsername(String username) { this.username = username; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
    public String getLastTaskStatus() { return lastTaskStatus; }
    public void setLastTaskStatus(String lastTaskStatus) { this.lastTaskStatus = lastTaskStatus; }
}
