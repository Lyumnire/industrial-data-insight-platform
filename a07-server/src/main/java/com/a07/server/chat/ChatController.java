// AI-assisted
package com.a07.server.chat;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import com.a07.server.config.AgentClient;

import jakarta.servlet.ServletOutputStream;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;

/**
 * S4 会话与任务：POST /api/chat/analyze（docs/03 §3.2、§5 时序）。
 * JWT 由 Security 过滤器统一校验；本控制器构造引擎请求体后向引擎透传 SSE。
 *
 * <p>透传纪律（T-016 更新）：响应体仍为<b>字节级搬运</b>，不改写 SSE 事件内容；
 * 同时在泵内解析事件写入 platform 库（S4 归档，工单推荐方案，不改引擎 routes.py）。
 * 引擎不可达/响应头超时 → 502 统一 JSON，不崩溃；引擎 4xx/5xx → 原状态码与错误体透传。</p>
 */
@RestController
public class ChatController {

    private static final Logger log = LoggerFactory.getLogger(ChatController.class);

    private static final String ENGINE_DOWN_MESSAGE = "Agent 引擎不可达，请确认引擎已启动或稍后重试";

    private final AgentClient agentClient;
    private final SseArchiveService archiveService;

    public ChatController(AgentClient agentClient, SseArchiveService archiveService) {
        this.agentClient = agentClient;
        this.archiveService = archiveService;
    }

    @PostMapping(value = "/api/chat/analyze", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public void analyze(@Valid @RequestBody ChatRequest request, HttpServletResponse response) throws IOException {
        AgentAnalyzeRequest engineRequest = toEngineRequest(request);

        AgentClient.UpstreamResponse upstream;
        try {
            upstream = agentClient.openAnalyzeStream(engineRequest);
        } catch (Exception engineUnreachable) {
            // 连接被拒 / 等待响应头超时等引擎不可达场景：502 而非崩溃（红线 R8）
            log.error("engine_unreachable sessionId={} type={} reason={}", engineRequest.sessionId(),
                    engineUnreachable.getClass().getSimpleName(), engineUnreachable.getMessage());
            writeJson(response, HttpStatus.BAD_GATEWAY.value(),
                    ("{\"code\":502,\"message\":\"" + ENGINE_DOWN_MESSAGE + "\",\"data\":null}")
                            .getBytes(StandardCharsets.UTF_8));
            return;
        }

        if (upstream.status() >= 400) {
            // 引擎明确返回错误状态：原状态码与错误体透传
            log.warn("engine_error_status status={} sessionId={}", upstream.status(), engineRequest.sessionId());
            try (InputStream errBody = upstream.body()) {
                writeJson(response, upstream.status(), errBody.readAllBytes());
            }
            return;
        }

        streamUpstream(response, upstream, engineRequest.sessionId(),
                engineRequest.question(), currentUsername());
    }

    /** 补齐引擎请求体缺省字段并透传 history（docs/03 §4 请求契约）。 */
    private static AgentAnalyzeRequest toEngineRequest(ChatRequest request) {
        return new AgentAnalyzeRequest(
                org.springframework.util.StringUtils.hasText(request.sessionId())
                        ? request.sessionId() : UUID.randomUUID().toString(),
                org.springframework.util.StringUtils.hasText(request.messageId())
                        ? request.messageId() : UUID.randomUUID().toString(),
                request.question(),
                request.history() == null ? List.of() : request.history());
    }

    /** 从 SecurityContext 取当前登录用户名；无认证时返回 null。 */
    private static String currentUsername() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        return (auth != null && auth.isAuthenticated()) ? auth.getName() : null;
    }

    /**
     * 把引擎响应状态/头写回客户端，阻塞逐块原样搬运 body 字节流。
     * 同时将字节喂入 SSE 归档服务（S4，评分点4）——归档失败不影响透传。
     * 客户端断开或上游中断时终止搬运并关闭上游连接（状态码已提交，仅记日志）。
     */
    private void streamUpstream(HttpServletResponse response,
                                AgentClient.UpstreamResponse upstream,
                                String sessionId,
                                String question,
                                String username) throws IOException {
        response.setStatus(upstream.status());
        response.setContentType(upstream.contentType() == null
                ? MediaType.TEXT_EVENT_STREAM_VALUE
                : upstream.contentType());
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());

        // S4 归档：泵开始前建立会话/任务记录
        SseArchiveService.ArchiveSession archive =
                archiveService.beginSession(sessionId, question, username);

        boolean streamBroken = false;
        ServletOutputStream out = response.getOutputStream();
        try (InputStream in = upstream.body()) {
            byte[] buffer = new byte[4096];
            int n;
            while ((n = in.read(buffer)) != -1) {
                out.write(buffer, 0, n);
                out.flush();
                // 归档侧只读，不影响透传字节
                archive.onBytes(buffer, 0, n);
            }
        } catch (IOException clientOrUpstreamBroken) {
            // SSE 流中途断开：状态码已提交，仅记录（引擎侧以 error 事件兜底）
            streamBroken = true;
            log.error("engine_stream_broken sessionId={} reason={}", sessionId,
                    clientOrUpstreamBroken.toString());
        } finally {
            archive.finish(streamBroken);
        }
        log.info("engine_analyze_end sessionId={}", sessionId);
    }

    private static void writeJson(HttpServletResponse response, int status, byte[] body) throws IOException {
        response.setStatus(status);
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.getOutputStream().write(body);
    }
}
