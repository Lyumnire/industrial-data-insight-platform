// AI-assisted
package com.a07.server.agent;

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
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * BUG-021 引擎不可达场景：POST /api/agent/ml/run 在引擎未启动时返回 502 而非崩溃，
 * body.message 可读（对齐 BUG-012 / ChatProxyEngineDownTests）。
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class MlRunProxyEngineDownTests {

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
    @DisplayName("带合法 JWT 但引擎未启动：502 + 可读 message，服务不崩溃")
    void ml_run_with_jwt_when_engine_down_returns_502() {
        String token = loginAsAdmin();

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.setBearerAuth(token);

        String requestBody =
                "{\"model_type\":\"random_forest\",\"features\":[\"f1\"],\"target\":\"y\","
                        + "\"parameters\":{},\"data_ref\":\"/tmp/demo.csv\"}";

        ResponseEntity<JsonNode> response = rest.exchange("/api/agent/ml/run", HttpMethod.POST,
                new HttpEntity<>(requestBody, headers), JsonNode.class);

        assertEquals(502, response.getStatusCode().value(), "引擎不可达必须返回 502");
        assertNotNullBody(response.getBody());
        assertEquals(502, response.getBody().path("code").asInt());
        assertTrue(response.getBody().path("message").asText().contains("引擎不可达"),
                "502 body.message 应可读且指明引擎不可达，实际 "
                        + response.getBody().path("message").asText());
    }

    private static void assertNotNullBody(JsonNode body) {
        assertTrue(body != null && !body.isMissingNode() && !body.isNull(),
                "502 响应必须带 JSON body");
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
