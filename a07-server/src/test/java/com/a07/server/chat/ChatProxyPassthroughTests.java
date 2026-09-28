// AI-assisted
package com.a07.server.chat;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import com.fasterxml.jackson.databind.JsonNode;
import com.sun.net.httpserver.HttpServer;

import com.a07.server.config.AgentClient;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * SSE 透传契约测试（工单边界：透传层不得改写 SSE 事件内容）。
 * 用 JDK 内置 HttpServer 模拟引擎，断言 a07-server 返回体与引擎字节级一致，
 * 且转发给引擎的请求体按 docs/03 §4 契约构造（sessionId/messageId/question/history）。
 * T-016 更新：泵内解析事件用于 S4 归档，但不改写透传字节。
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class ChatProxyPassthroughTests {

    /** 引擎将返回的原始 SSE 字节序列（含中文字符，验证非 ASCII 也不被改写）。 */
    private static final String ENGINE_SSE_BODY =
            "event: task_started\ndata: {\"stepId\":\"1\",\"name\":\"意图理解\"}\n\n"
                    + "event: text_delta\ndata: {\"delta\":\"各工序良率如下\"}\n\n"
                    + "event: done\ndata: {\"summary\":{}}\n\n";

    private static final AtomicReference<String> RECORDED_REQUEST = new AtomicReference<>();

    /** 类加载即启动假引擎，保证 @DynamicPropertySource 取值时端口已就绪。 */
    private static final HttpServer ENGINE = startFakeEngine();

    @DynamicPropertySource
    static void agentProps(DynamicPropertyRegistry registry) {
        registry.add("agent.base-url",
                () -> "http://127.0.0.1:" + ENGINE.getAddress().getPort());
    }

    @AfterAll
    static void stopFakeEngine() {
        ENGINE.stop(0);
    }

    private static HttpServer startFakeEngine() {
        try {
            HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
            server.createContext(AgentClient.ANALYZE_PATH, exchange -> {
                String requestBody = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
                RECORDED_REQUEST.set(requestBody);
                exchange.getResponseHeaders().set("Content-Type", "text/event-stream; charset=UTF-8");
                if (requestBody.contains("\"slow-s1\"")) {
                    // 慢帧模式：模拟真实 LLM 场景——首帧后长间隔再发后续帧（T8 联调修复的回归锚点）
                    exchange.sendResponseHeaders(200, 0);
                    try (OutputStream out = exchange.getResponseBody()) {
                        for (String frame : ENGINE_SSE_BODY.split("(?=\n\n)")) {
                            out.write(frame.getBytes(StandardCharsets.UTF_8));
                            out.flush();
                            try {
                                Thread.sleep(300);
                            } catch (InterruptedException interrupted) {
                                Thread.currentThread().interrupt();
                                return;
                            }
                        }
                    }
                    return;
                }
                byte[] response = ENGINE_SSE_BODY.getBytes(StandardCharsets.UTF_8);
                exchange.sendResponseHeaders(200, response.length);
                try (OutputStream out = exchange.getResponseBody()) {
                    out.write(response);
                }
            });
            server.start();
            return server;
        } catch (IOException e) {
            throw new IllegalStateException("测试假引擎启动失败", e);
        }
    }

    @Autowired
    private TestRestTemplate rest;

    @Test
    @DisplayName("透传：响应 200 + text/event-stream + 与引擎输出字节级一致")
    void passthrough_is_byte_identical() {
        String token = loginAsAdmin();

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.setAccept(java.util.List.of(MediaType.TEXT_EVENT_STREAM));
        headers.setBearerAuth(token);

        ResponseEntity<byte[]> response = rest.exchange("/api/chat/analyze", org.springframework.http.HttpMethod.POST,
                new HttpEntity<>(Map.of("question", "请分析各工序的良率"), headers), byte[].class);

        assertEquals(200, response.getStatusCode().value());
        assertNotNull(response.getBody());
        assertTrue(response.getHeaders().getContentType().isCompatibleWith(MediaType.TEXT_EVENT_STREAM),
                "Content-Type 应保持 text/event-stream，实际 " + response.getHeaders().getContentType());
        // 字节级一致 ⇒ 透传层未解析、未改写任何事件内容
        assertEquals(ENGINE_SSE_BODY, new String(response.getBody(), StandardCharsets.UTF_8));
    }

    @Test
    @DisplayName("转发给引擎的请求体按契约构造：补齐 messageId/sessionId，question 原样")
    void engine_request_is_constructed_per_contract() {
        String token = loginAsAdmin();

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.setBearerAuth(token);
        rest.exchange("/api/chat/analyze", org.springframework.http.HttpMethod.POST,
                new HttpEntity<>(Map.of("sessionId", "s-1001", "question", "最近7天产量趋势"), headers),
                byte[].class);

        String recorded = RECORDED_REQUEST.get();
        assertNotNull(recorded, "引擎应收到请求");
        assertTrue(recorded.contains("\"sessionId\":\"s-1001\""));
        assertTrue(recorded.contains("\"messageId\":\""));
        assertTrue(recorded.contains("\"question\":\"最近7天产量趋势\""));
        assertTrue(recorded.contains("\"history\":[]"));
    }

    @Test
    @DisplayName("透传：慢帧（LLM 长间隔）场景下全部事件仍完整到达且字节级一致")
    void passthrough_survives_slow_chunks() {
        String token = loginAsAdmin();

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.setAccept(java.util.List.of(MediaType.TEXT_EVENT_STREAM));
        headers.setBearerAuth(token);

        ResponseEntity<byte[]> response = rest.exchange("/api/chat/analyze", org.springframework.http.HttpMethod.POST,
                new HttpEntity<>(Map.of("sessionId", "slow-s1", "question", "请分析各工序的良率"), headers),
                byte[].class);

        assertEquals(200, response.getStatusCode().value());
        assertNotNull(response.getBody());
        assertEquals(ENGINE_SSE_BODY, new String(response.getBody(), StandardCharsets.UTF_8),
                "慢帧间隔下不应丢帧、不应被超时截断");
    }

    @Test
    @DisplayName("缺 question：400（校验先于引擎调用）")
    void missing_question_returns_400() {
        String token = loginAsAdmin();

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.setAccept(java.util.List.of(MediaType.TEXT_EVENT_STREAM));
        headers.setBearerAuth(token);

        var response = rest.postForEntity("/api/chat/analyze",
                new HttpEntity<>(Map.of("sessionId", "s-1002"), headers), JsonNode.class);

        assertEquals(400, response.getStatusCode().value());
        assertNotNull(response.getBody());
        assertEquals(400, response.getBody().path("code").asInt());
    }

    private String loginAsAdmin() {
        var response = rest.postForEntity("/api/auth/login",
                Map.of("username", "admin", "password", "admin123"), JsonNode.class);
        assertEquals(200, response.getStatusCode().value());
        String token = response.getBody().path("data").path("token").asText();
        assertTrue(!token.isBlank());
        return token;
    }
}
