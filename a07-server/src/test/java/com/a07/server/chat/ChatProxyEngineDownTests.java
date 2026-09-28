// AI-assisted
package com.a07.server.chat;

import java.net.ServerSocket;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 引擎不可达场景（工单验收：POST /api/chat/analyze 在引擎未启动时返回 502 而非崩溃）。
 * agent.base-url 指向一个确定无人监听的端口，模拟引擎未启动。
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class ChatProxyEngineDownTests {

    /** 先占用再释放，得到一个确定空闲（连接必被拒）的端口。 */
    private static final int CLOSED_PORT = findClosedPort();

    @DynamicPropertySource
    static void agentProps(DynamicPropertyRegistry registry) {
        registry.add("agent.base-url", () -> "http://127.0.0.1:" + CLOSED_PORT);
    }

    private static int findClosedPort() {
        try (ServerSocket socket = new ServerSocket(0)) {
            return socket.getLocalPort();
        } catch (Exception e) {
            throw new IllegalStateException("无法获取空闲端口用于模拟引擎不可达", e);
        }
    }

    @Autowired
    private TestRestTemplate rest;

    @Test
    @DisplayName("带合法 JWT 但引擎未启动：502 + 统一错误体，服务不崩溃")
    void analyze_with_jwt_when_engine_down_returns_502() {
        String token = loginAsAdmin();

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.setAccept(java.util.List.of(MediaType.TEXT_EVENT_STREAM));
        headers.setBearerAuth(token);

        var response = rest.postForEntity("/api/chat/analyze",
                new HttpEntity<>(Map.of("question", "请分析各工序的良率"), headers), JsonNode.class);

        assertEquals(502, response.getStatusCode().value(), "引擎不可达必须返回 502");
        assertEquals(502, response.getBody().path("code").asInt());
        assertTrue(response.getBody().path("message").asText().contains("引擎不可达"));
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
