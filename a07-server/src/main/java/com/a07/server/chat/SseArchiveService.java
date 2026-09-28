// AI-assisted
package com.a07.server.chat;

import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * SSE 事件归档服务（S4，评分点4）：
 * 在 ChatController 透传泵内解析 step/plan/sql/table/report/done 等事件，
 * 写入 chat_sessions/chat_messages/analysis_tasks/analysis_steps/analysis_results。
 * 归档失败仅记日志，不阻断 SSE 流（透传优先）。
 */
@Service
public class SseArchiveService {

    private static final Logger log = LoggerFactory.getLogger(SseArchiveService.class);

    private final ChatSessionMapper sessionMapper;
    private final ChatMessageMapper messageMapper;
    private final AnalysisTaskMapper taskMapper;
    private final AnalysisStepMapper stepMapper;
    private final AnalysisResultMapper resultMapper;
    private final ObjectMapper objectMapper;

    /** 每次 analyze 请求的归档上下文（线程安全：每次调用独立实例）。 */
    private static final class ArchiveContext {
        String sessionId;
        String question;
        String username;
        Long taskId;
        String planJson;
        String reportMarkdown;
        final StringBuilder textBuffer = new StringBuilder();
        final Map<String, AnalysisStepEntity> stepMap = new ConcurrentHashMap<>();
        boolean taskCreated;
        boolean done;
    }

    public SseArchiveService(ChatSessionMapper sessionMapper, ChatMessageMapper messageMapper,
                             AnalysisTaskMapper taskMapper, AnalysisStepMapper stepMapper,
                             AnalysisResultMapper resultMapper, ObjectMapper objectMapper) {
        this.sessionMapper = sessionMapper;
        this.messageMapper = messageMapper;
        this.taskMapper = taskMapper;
        this.stepMapper = stepMapper;
        this.resultMapper = resultMapper;
        this.objectMapper = objectMapper;
    }

    /** 创建归档上下文（在 pump 开始前调用）。 */
    public ArchiveSession beginSession(String sessionId, String question, String username) {
        return new ArchiveSession(sessionId, question, username, this);
    }

    /**
     * 归档会话句柄：泵内逐事件调用 onEvent，流结束后调用 finish。
     * 所有方法吞异常仅记日志，保证不影响 SSE 透传。
     */
    public static final class ArchiveSession {
        private final SseArchiveService service;
        private final ArchiveContext ctx;

        ArchiveSession(String sessionId, String question, String username, SseArchiveService service) {
            this.service = service;
            this.ctx = new ArchiveContext();
            this.ctx.sessionId = sessionId;
            this.ctx.question = question;
            this.ctx.username = username;
            try {
                service.ensureSession(sessionId, question, username);
                service.ensureTask(ctx);
            } catch (Exception e) {
                log.warn("sse_archive_begin_failed sessionId={} reason={}", sessionId, e.getMessage());
            }
        }

        /** 泵内收到一块原始字节时调用；内部做 SSE 帧解析。 */
        public void onBytes(byte[] buffer, int offset, int length) {
            try {
                service.feedBytes(ctx, buffer, offset, length);
            } catch (Exception e) {
                log.warn("sse_archive_feed_failed sessionId={} reason={}", ctx.sessionId, e.getMessage());
            }
        }

        /** 流结束（正常或异常）时调用，写入最终状态与消息。 */
        public void finish(boolean streamBroken) {
            try {
                service.finishContext(ctx, streamBroken);
            } catch (Exception e) {
                log.warn("sse_archive_finish_failed sessionId={} reason={}", ctx.sessionId, e.getMessage());
            }
        }
    }

    // ==================== 内部实现 ====================

    private final ThreadLocal<StringBuilder> frameBuffer = ThreadLocal.withInitial(StringBuilder::new);

    void ensureSession(String sessionId, String question, String username) {
        ChatSessionEntity existing = sessionMapper.selectOne(new LambdaQueryWrapper<ChatSessionEntity>()
                .eq(ChatSessionEntity::getSessionId, sessionId));
        if (existing == null) {
            ChatSessionEntity s = new ChatSessionEntity();
            s.setSessionId(sessionId);
            s.setTitle(truncate(question, 200));
            s.setUsername(username);
            s.setCreatedAt(LocalDateTime.now());
            sessionMapper.insert(s);
        } else if (existing.getTitle() == null || existing.getTitle().isBlank()) {
            existing.setTitle(truncate(question, 200));
            sessionMapper.updateById(existing);
        }
    }

    void ensureTask(ArchiveContext ctx) {
        if (ctx.taskCreated) {
            return;
        }
        AnalysisTaskEntity task = new AnalysisTaskEntity();
        task.setSessionId(ctx.sessionId);
        task.setQuestion(ctx.question == null ? "" : truncate(ctx.question, 500));
        task.setStatus("running");
        task.setCreatedAt(LocalDateTime.now());
        taskMapper.insert(task);
        ctx.taskId = task.getId();
        ctx.taskCreated = true;

        // 归档用户消息
        ChatMessageEntity userMsg = new ChatMessageEntity();
        userMsg.setSessionId(ctx.sessionId);
        userMsg.setRole("user");
        userMsg.setContent(ctx.question);
        userMsg.setEventRef(String.valueOf(ctx.taskId));
        userMsg.setCreatedAt(LocalDateTime.now());
        messageMapper.insert(userMsg);
    }

    /**
     * 喂入原始字节，按 SSE 协议（event: X\ndata: JSON\n\n）解析并归档事件。
     * 字节级透传不受影响——本方法只读缓冲，不修改 output。
     */
    void feedBytes(ArchiveContext ctx, byte[] buffer, int offset, int length) {
        String chunk = new String(buffer, offset, length, StandardCharsets.UTF_8);
        StringBuilder sb = frameBuffer.get();
        sb.append(chunk);

        // SSE 帧以 \n\n 分隔
        int idx;
        while ((idx = sb.indexOf("\n\n")) >= 0) {
            String frame = sb.substring(0, idx);
            sb.delete(0, idx + 2);
            processFrame(ctx, frame);
        }
    }

    private void processFrame(ArchiveContext ctx, String frame) {
        String eventType = null;
        String dataLine = null;
        for (String line : frame.split("\n")) {
            if (line.startsWith("event:")) {
                eventType = line.substring(6).trim();
            } else if (line.startsWith("data:")) {
                dataLine = line.substring(5).trim();
            }
        }
        if (eventType == null || dataLine == null) {
            return;
        }
        try {
            JsonNode data = objectMapper.readTree(dataLine);
            handleEvent(ctx, eventType, data);
        } catch (Exception e) {
            log.debug("sse_event_parse_failed type={} reason={}", eventType, e.getMessage());
        }
    }

    private void handleEvent(ArchiveContext ctx, String eventType, JsonNode data) {
        switch (eventType) {
            case "plan_ready" -> {
                ctx.planJson = data.toString();
                updateTaskPlan(ctx);
            }
            case "step_started" -> archiveStepStart(ctx, data);
            case "step_finished" -> archiveStepFinish(ctx, data);
            case "text_delta" -> {
                if (data.hasNonNull("delta")) {
                    ctx.textBuffer.append(data.get("delta").asText());
                }
            }
            case "report" -> {
                if (data.hasNonNull("markdown")) {
                    ctx.reportMarkdown = data.get("markdown").asText();
                } else if (data.hasNonNull("content")) {
                    ctx.reportMarkdown = data.get("content").asText();
                }
            }
            case "done" -> handleDone(ctx, data);
            case "error" -> handleError(ctx, data);
            default -> { /* 其他事件如 sql/chart/table 暂不单独归档 */ }
        }
    }

    private void archiveStepStart(ArchiveContext ctx, JsonNode data) {
        if (ctx.taskId == null) {
            return;
        }
        String stepId = data.hasNonNull("stepId") ? data.get("stepId").asText() : "unknown";
        String name = data.hasNonNull("name") ? data.get("name").asText() : stepId;
        String detail = data.hasNonNull("detail") ? data.get("detail").asText() : null;

        AnalysisStepEntity step = new AnalysisStepEntity();
        step.setTaskId(ctx.taskId);
        step.setStepId(stepId);
        step.setName(truncate(name, 100));
        step.setDetail(truncate(detail, 500));
        step.setStartedAt(LocalDateTime.now());
        stepMapper.insert(step);
        ctx.stepMap.put(stepId, step);
    }

    private void archiveStepFinish(ArchiveContext ctx, JsonNode data) {
        String stepId = data.hasNonNull("stepId") ? data.get("stepId").asText() : "unknown";
        AnalysisStepEntity step = ctx.stepMap.get(stepId);
        if (step == null) {
            // 引擎可能只发 finished 没有 started：补建
            if (ctx.taskId == null) {
                return;
            }
            step = new AnalysisStepEntity();
            step.setTaskId(ctx.taskId);
            step.setStepId(stepId);
            step.setName(data.hasNonNull("name") ? data.get("name").asText() : stepId);
            step.setDetail(data.hasNonNull("detail") ? data.get("detail").asText() : null);
            step.setStartedAt(LocalDateTime.now());
        }
        step.setFinishedAt(LocalDateTime.now());
        if (step.getId() != null) {
            stepMapper.updateById(step);
        } else {
            stepMapper.insert(step);
        }
        ctx.stepMap.put(stepId, step);
    }

    private void updateTaskPlan(ArchiveContext ctx) {
        if (ctx.taskId == null || ctx.planJson == null) {
            return;
        }
        AnalysisTaskEntity task = taskMapper.selectById(ctx.taskId);
        if (task != null) {
            task.setPlanJson(ctx.planJson);
            taskMapper.updateById(task);
        }
    }

    private void handleDone(ArchiveContext ctx, JsonNode data) {
        if (ctx.taskId == null || ctx.done) {
            return;
        }
        ctx.done = true;

        AnalysisTaskEntity task = taskMapper.selectById(ctx.taskId);
        if (task == null) {
            return;
        }
        task.setStatus("completed");
        if (data.hasNonNull("durationMs")) {
            task.setDurationMs(data.get("durationMs").asLong());
        }
        if (data.hasNonNull("tokensCost")) {
            task.setTokensCost(data.get("tokensCost").asLong());
        }
        taskMapper.updateById(task);

        // 归档分析结果
        AnalysisResultEntity result = new AnalysisResultEntity();
        result.setTaskId(ctx.taskId);
        result.setStandardResultJson(data.toString());
        result.setReportMarkdown(ctx.reportMarkdown);
        result.setCreatedAt(LocalDateTime.now());
        resultMapper.insert(result);

        task.setResultRef(String.valueOf(result.getId()));
        taskMapper.updateById(task);

        // 归档 assistant 消息（结论文本）
        String assistantContent = ctx.textBuffer.length() > 0
                ? ctx.textBuffer.toString()
                : (ctx.reportMarkdown != null ? ctx.reportMarkdown : data.toString());
        ChatMessageEntity assistantMsg = new ChatMessageEntity();
        assistantMsg.setSessionId(ctx.sessionId);
        assistantMsg.setRole("assistant");
        assistantMsg.setContent(truncate(assistantContent, 10000));
        assistantMsg.setEventRef(String.valueOf(ctx.taskId));
        assistantMsg.setCreatedAt(LocalDateTime.now());
        messageMapper.insert(assistantMsg);
    }

    private void handleError(ArchiveContext ctx, JsonNode data) {
        if (ctx.taskId == null || ctx.done) {
            return;
        }
        ctx.done = true;
        AnalysisTaskEntity task = taskMapper.selectById(ctx.taskId);
        if (task != null) {
            task.setStatus("failed");
            taskMapper.updateById(task);
        }
        String errMsg = data.hasNonNull("message") ? data.get("message").asText() : "引擎错误";
        ChatMessageEntity assistantMsg = new ChatMessageEntity();
        assistantMsg.setSessionId(ctx.sessionId);
        assistantMsg.setRole("assistant");
        assistantMsg.setContent("[error] " + errMsg);
        assistantMsg.setEventRef(String.valueOf(ctx.taskId));
        assistantMsg.setCreatedAt(LocalDateTime.now());
        messageMapper.insert(assistantMsg);
    }

    private void finishContext(ArchiveContext ctx, boolean streamBroken) {
        if (ctx.taskId == null || ctx.done) {
            return;
        }
        // 流断开且未收到 done/error → 标记失败
        AnalysisTaskEntity task = taskMapper.selectById(ctx.taskId);
        if (task != null && "running".equals(task.getStatus())) {
            task.setStatus(streamBroken ? "failed" : "completed");
            taskMapper.updateById(task);
        }
        // 若有累积文本但没收到 done，也归档为 assistant 消息
        if (ctx.textBuffer.length() > 0) {
            ChatMessageEntity assistantMsg = new ChatMessageEntity();
            assistantMsg.setSessionId(ctx.sessionId);
            assistantMsg.setRole("assistant");
            assistantMsg.setContent(truncate(ctx.textBuffer.toString(), 10000));
            assistantMsg.setEventRef(String.valueOf(ctx.taskId));
            assistantMsg.setCreatedAt(LocalDateTime.now());
            messageMapper.insert(assistantMsg);
        }
        frameBuffer.remove();
    }

    private static String truncate(String s, int maxLen) {
        if (s == null) return null;
        return s.length() <= maxLen ? s : s.substring(0, maxLen);
    }
}
