// AI-assisted
package com.a07.server.chat;

import java.util.List;

/**
 * a07-server → a07-agent 的分析请求体。
 * 字段与引擎实现严格对齐：a07-agent/app/api/routes.py#AnalyzeRequest
 * （sessionId/messageId/question/history；docs/03 §4 请求契约）。
 */
public record AgentAnalyzeRequest(String sessionId, String messageId, String question,
                                  List<ChatRequest.HistoryMessage> history) {
}
