// AI-assisted
package com.a07.server.chat;

import java.util.List;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;

/**
 * 前端 → a07-server 的分析请求体（docs/03 §4 边界：S4 负责构造引擎请求体）。
 * sessionId/messageId 缺省时由服务端补 UUID；history 为多轮历史（P1 透传，P2 由 S4 做指代消解）。
 */
public record ChatRequest(

        String sessionId,

        String messageId,

        @NotBlank(message = "问题不能为空") String question,

        @Valid List<HistoryMessage> history) {

    /** 多轮历史消息（role: user/assistant）。 */
    public record HistoryMessage(String role, String content) {
    }
}
