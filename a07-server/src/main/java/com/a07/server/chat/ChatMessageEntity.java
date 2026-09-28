// AI-assisted
package com.a07.server.chat;

import java.time.LocalDateTime;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

/** chat_messages 表实体（V2）。 */
@TableName("chat_messages")
public class ChatMessageEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String sessionId;

    /** user | assistant | system */
    private String role;

    private String content;

    private String eventRef;

    private LocalDateTime createdAt;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getSessionId() { return sessionId; }
    public void setSessionId(String sessionId) { this.sessionId = sessionId; }
    public String getRole() { return role; }
    public void setRole(String role) { this.role = role; }
    public String getContent() { return content; }
    public void setContent(String content) { this.content = content; }
    public String getEventRef() { return eventRef; }
    public void setEventRef(String eventRef) { this.eventRef = eventRef; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
}
