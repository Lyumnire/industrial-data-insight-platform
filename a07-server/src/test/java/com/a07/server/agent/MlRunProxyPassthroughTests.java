// AI-assisted
package com.a07.server.agent;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;

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
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * BUG-021：POST /api/agent/ml/run 代理透传契约测试。
 * 用 JDK 内置 HttpServer 模拟引擎，断言 a07-server 字节级转发请求/响应，
 * 引擎 4xx 原样透传；仿 ChatProxyPassthroughTests。
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class MlRunProxyPassthroughTests {

    /** 引擎将返回的原始 JSON（含 camelCase + snake_case 双形态，对齐 ml_payload）。 */
    private static final String ENGINE_ML_BODY =
            "{\"task_id\":\"ml-t-001\",\"model_type\":\"random_forest\",\"task_type\":\"regression\","
                    + "\"metrics\":{\"r2\":0.91,\"mae\":0.12},"
                    + "\"featureImportance\":[{\"name\":\"f1\",\"score\":0.62}],"
                    + "\"taskId\":\"ml-t-001\",\"modelType\":\"random_forest\",\"taskType\":\"regression\","
                    + "\"modelPath\":\"models/rf-001.joblib\",\"warnings\":[]}";

    private static final String ENGINE_ERROR_BODY =
            "{\"detail\":\"data_ref 文件不存在: /tmp/no_such.csv\"}";

    private static final AtomicReference<String> RECORDED_REQUEST = new AtomicReference<>();
    private static final AtomicReference<String> RECORDED_CONTENT_TYPE = new AtomicReference<>();

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
            server.createContext(AgentClient.ML_RUN_PATH, exchange -> {
                String requestBody = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
                RECORDED_REQUEST.set(requestBody);
                RECORDED_CONTENT_TYPE.set(exchange.getRequestHeaders().getFirst("Content-Type"));

                exchange.getResponseHeaders().set("Content-Type", "application/json");
                if (requestBody.contains("no_such.csv")) {
                    // 模拟引擎数据校验失败（FastAPI HTTPException 400 detail 形态）
                    byte[] err = ENGINE_ERROR_BODY.getBytes(StandardCharsets.UTF_8);
                    exchange.sendResponseHeaders(400, err.length);
                    try (OutputStream out = exchange.getResponseBody()) {
                        out.write(err);
                    }
                    return;
                }
                byte[] response = ENGINE_ML_BODY.getBytes(StandardCharsets.UTF_8);
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
    @DisplayName("BUG-021 透传：200 + 引擎 ml_payload 字节级一致，请求体原样转发")
    void ml_run_passthrough_is_byte_identical() {
        String token = loginAsAdmin();

        String requestBody =
                "{\"model_type\":\"random_forest\",\"features\":[\"f1\",\"f2\"],\"target\":\"y\","
                        + "\"parameters\":{\"n_estimators\":50},"
                        + "\"data_ref\":\"/tmp/demo.csv\",\"question\":\"哪些因素影响产量\"}";

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.setBearerAuth(token);

        ResponseEntity<byte[]> response = rest.exchange("/api/agent/ml/run", HttpMethod.POST,
                new HttpEntity<>(requestBody, headers), byte[].class);

        assertEquals(200, response.getStatusCode().value());
        assertNotNull(response.getBody());
        assertEquals(ENGINE_ML_BODY, new String(response.getBody(), StandardCharsets.UTF_8),
                "代理层不得改写引擎 ml_payload");
        assertTrue(response.getHeaders().getContentType().isCompatibleWith(MediaType.APPLICATION_JSON),
                "Content-Type 应保持 application/json，实际 " + response.getHeaders().getContentType());

        String recorded = RECORDED_REQUEST.get();
        assertNotNull(recorded, "引擎应收到请求");
        assertEquals(requestBody, recorded, "请求体应字节级转发给引擎");
        assertTrue(RECORDED_CONTENT_TYPE.get() != null
                        && RECORDED_CONTENT_TYPE.get().contains("application/json"),
                "转发 Content-Type 应为 application/json");
    }

    @Test
    @DisplayName("BUG-021 引擎 400：原状态码与错误体透传（数据校验失败可读）")
    void ml_run_engine_error_is_passed_through() {
        String token = loginAsAdmin();

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.setBearerAuth(token);

        String requestBody =
                "{\"model_type\":\"kmeans\",\"features\":[\"x1\"],\"target\":null,"
                        + "\"parameters\":{},\"data_ref\":\"/tmp/no_such.csv\"}";

        ResponseEntity<byte[]> response = rest.exchange("/api/agent/ml/run", HttpMethod.POST,
                new HttpEntity<>(requestBody, headers), byte[].class);

        assertEquals(400, response.getStatusCode().value(), "引擎 4xx 应原样透传");
        assertNotNull(response.getBody());
        assertEquals(ENGINE_ERROR_BODY, new String(response.getBody(), StandardCharsets.UTF_8),
                "引擎错误体不得被改写为统一 500");
    }

    private String loginAsAdmin() {
        var response = rest.postForEntity("/api/auth/login",
                java.util.Map.of("username", "admin", "password", "admin123"),
                com.fasterxml.jackson.databind.JsonNode.class);
        assertEquals(200, response.getStatusCode().value());
        String token = response.getBody().path("data").path("token").asText();
        assertTrue(!token.isBlank());
        return token;
    }
}
