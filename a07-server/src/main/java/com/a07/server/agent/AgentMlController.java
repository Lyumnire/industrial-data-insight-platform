// AI-assisted
package com.a07.server.agent;

import java.nio.charset.StandardCharsets;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import com.a07.server.config.AgentClient;

/**
 * S4 → 引擎建模直调代理（BUG-021 / docs/03 §3.3 A7）。
 * JWT 由 Security 过滤器统一校验（authenticated）；请求/响应 JSON <b>字节级透传</b>，
 * 不解析不改写引擎 ml_payload（前端兼容直出与 {code,message,data} 两种形态）。
 *
 * <p>错误映射（对齐 BUG-012 / ChatController，红线 R8）：
 * 引擎不可达/超时 → 502 + 可读 message；引擎 4xx/5xx → 原状态码与错误体原样透传
 * （如 FastAPI 400 {@code {"detail":"..."}}，前端直接展示）。</p>
 */
@RestController
public class AgentMlController {

    private static final Logger log = LoggerFactory.getLogger(AgentMlController.class);

    /** 与 ChatController 一致的引擎不可达文案（BUG-012：前端优先读 body.message）。 */
    private static final String ENGINE_DOWN_MESSAGE = "Agent 引擎不可达，请确认引擎已启动或稍后重试";

    private final AgentClient agentClient;

    public AgentMlController(AgentClient agentClient) {
        this.agentClient = agentClient;
    }

    @PostMapping(value = "/api/agent/ml/run", consumes = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<byte[]> mlRun(@RequestBody(required = false) byte[] body) {
        AgentClient.JsonUpstreamResponse upstream;
        try {
            upstream = agentClient.postMlRun(body);
        } catch (Exception engineUnreachable) {
            // 连接被拒 / 等待响应超时等引擎不可达场景：502 而非崩溃（红线 R8）
            log.error("engine_ml_run_unreachable type={} reason={}",
                    engineUnreachable.getClass().getSimpleName(), engineUnreachable.getMessage());
            byte[] errorBody = ("{\"code\":502,\"message\":\"" + ENGINE_DOWN_MESSAGE + "\",\"data\":null}")
                    .getBytes(StandardCharsets.UTF_8);
            return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(errorBody);
        }

        if (upstream.status() >= 400) {
            // 引擎明确返回错误：原状态码与错误体透传（建模数据校验失败等）
            log.warn("engine_ml_run_error status={}", upstream.status());
        }

        MediaType contentType = resolveContentType(upstream.contentType());
        byte[] responseBody = upstream.body() == null ? new byte[0] : upstream.body();
        return ResponseEntity.status(upstream.status())
                .contentType(contentType)
                .body(responseBody);
    }

    private static MediaType resolveContentType(String raw) {
        if (raw == null || raw.isBlank()) {
            return MediaType.APPLICATION_JSON;
        }
        try {
            return MediaType.parseMediaType(raw);
        } catch (Exception parseFail) {
            return MediaType.APPLICATION_JSON;
        }
    }
}
