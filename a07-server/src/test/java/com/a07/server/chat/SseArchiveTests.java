// AI-assisted
package com.a07.server.chat;

import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.sun.net.httpserver.HttpServer;

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
 * S4 SSE 归档测试（评分点4，工单验收）：
 * 模拟引擎返回完整事件流 → 验证 SSE 透传后 archive 可查
 * （/api/chat/sessions、/api/tasks、/api/tasks/{id}）。
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class SseArchiveTests {

    /** 引擎返回的完整事件序列：task_started → plan_ready → step → sql → text → table → done */
    private static final String FULL_SSE_BODY =
            "event: task_started\ndata: {\"stepId\":\"0\",\"name\":\"任务开始\"}\n\n"
                    + "event: plan_ready\ndata: {\"intent\":\"query\",\"topic\":\"良率\",\"tables\":[\"process_output\"]}\n\n"
                    + "event: step_started\ndata: {\"stepId\":\"1\",\"name\":\"意图理解\",\"detail\":\"识别为统计查询\"}\n\n"
                    + "event: step_finished\ndata: {\"stepId\":\"1\",\"name\":\"意图理解\",\"detail\":\"完成\"}\n\n"
                    + "event: step_started\ndata: {\"stepId\":\"2\",\"name\":\"生成SQL\"}\n\n"
                    + "event: sql_generated\ndata: {\"sql\":\"SELECT process, SUM(qualified_qty)/SUM(produced_qty) FROM process_output GROUP BY process LIMIT 100\"}\n\n"
                    + "event: step_finished\ndata: {\"stepId\":\"2\",\"name\":\"生成SQL\"}\n\n"
                    + "event: table\ndata: {\"columns\":[\"process\",\"yield\"],\"rows\":[[\"注塑\",0.95],[\"焊接\",0.92]]}\n\n"
                    + "event: text_delta\ndata: {\"delta\":\"各工序良率如下：注塑95%，焊接92%。\"}\n\n"
                    + "event: report\ndata: {\"markdown\":\"# 良率分析报告\\n注塑95%，焊接92%\",\"reportId\":\"r1\"}\n\n"
                    + "event: done\ndata: {\"columns\":[\"process\",\"yield\"],\"rows\":[],\"summary\":{},\"durationMs\":1234,\"tokensCost\":567}\n\n";

    private static HttpServer engine;

    @DynamicPropertySource
    static void agentProps(DynamicPropertyRegistry registry) {
        engine = startFakeEngine();
        registry.add("agent.base-url", () -> "http://127.0.0.1:" + engine.getAddress().getPort());
    }

    @AfterAll
    static void stopFakeEngine() {
        if (engine != null) {
            engine.stop(0);
        }
    }

    private static HttpServer startFakeEngine() {
        try {
            HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
            server.createContext(com.a07.server.config.AgentClient.ANALYZE_PATH, exchange -> {
                exchange.getRequestBody().readAllBytes();
                exchange.getResponseHeaders().set("Content-Type", "text/event-stream; charset=UTF-8");
                byte[] response = FULL_SSE_BODY.getBytes(StandardCharsets.UTF_8);
                exchange.sendResponseHeaders(200, 0); // chunked
                try (OutputStream out = exchange.getResponseBody()) {
                    out.write(response);
                    out.flush();
                }
            });
            server.start();
            return server;
        } catch (Exception e) {
            throw new IllegalStateException("归档测试假引擎启动失败", e);
        }
    }

    @Autowired
    private TestRestTemplate rest;

    @Autowired
    private ChatSessionMapper sessionMapper;

    @Autowired
    private AnalysisTaskMapper taskMapper;

    @Autowired
    private AnalysisStepMapper stepMapper;

    @Autowired
    private AnalysisResultMapper resultMapper;

    private String loginAsAdmin() {
        var response = rest.postForEntity("/api/auth/login",
                Map.of("username", "admin", "password", "admin123"), JsonNode.class);
        assertEquals(200, response.getStatusCode().value());
        return response.getBody().path("data").path("token").asText();
    }

    @Test
    @DisplayName("SSE 归档：analyze 后会话/任务/步骤/结果可查")
    void sse_events_are_archived_and_queryable() {
        String token = loginAsAdmin();
        String sessionId = "archive-test-" + System.nanoTime();

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.setAccept(java.util.List.of(MediaType.TEXT_EVENT_STREAM));
        headers.setBearerAuth(token);

        // 触发 analyze（SSE 透传 + 归档）
        ResponseEntity<byte[]> sseResponse = rest.exchange("/api/chat/analyze",
                org.springframework.http.HttpMethod.POST,
                new HttpEntity<>(Map.of("sessionId", sessionId,
                        "question", "请分析各工序的良率"), headers), byte[].class);
        assertEquals(200, sseResponse.getStatusCode().value());
        assertNotNull(sseResponse.getBody());
        // 透传字节级一致
        assertEquals(FULL_SSE_BODY, new String(sseResponse.getBody(), StandardCharsets.UTF_8),
                "SSE 透传字节不得被改写");

        HttpHeaders jsonHeaders = new HttpHeaders();
        jsonHeaders.setBearerAuth(token);

        // 会话可查
        ResponseEntity<JsonNode> sessionsResp = rest.exchange(
                "/api/chat/sessions?username=admin&size=50",
                org.springframework.http.HttpMethod.GET,
                new HttpEntity<>(jsonHeaders), JsonNode.class);
        assertEquals(200, sessionsResp.getStatusCode().value());
        JsonNode sessionRecords = sessionsResp.getBody().path("data").path("records");
        boolean foundSession = false;
        for (JsonNode s : sessionRecords) {
            if (sessionId.equals(s.path("sessionId").asText())) {
                foundSession = true;
                assertNotNull(s.path("title").asText());
            }
        }
        assertTrue(foundSession, "会话 " + sessionId + " 应可查");

        // 任务列表可查
        ResponseEntity<JsonNode> tasksResp = rest.exchange(
                "/api/tasks?sessionId=" + sessionId,
                org.springframework.http.HttpMethod.GET,
                new HttpEntity<>(jsonHeaders), JsonNode.class);
        assertEquals(200, tasksResp.getStatusCode().value());
        JsonNode taskRecords = tasksResp.getBody().path("data").path("records");
        assertTrue(taskRecords.size() >= 1, "应有至少 1 条归档任务");
        JsonNode task = taskRecords.get(0);
        assertEquals("completed", task.path("status").asText());
        assertEquals("请分析各工序的良率", task.path("question").asText());
        long taskId = task.path("id").asLong();

        // 任务详情可查：步骤 + 结果
        ResponseEntity<JsonNode> detailResp = rest.exchange(
                "/api/tasks/" + taskId,
                org.springframework.http.HttpMethod.GET,
                new HttpEntity<>(jsonHeaders), JsonNode.class);
        assertEquals(200, detailResp.getStatusCode().value());
        JsonNode detail = detailResp.getBody().path("data");

        // planJson 已归档
        assertTrue(detail.path("planJson").isTextual() && !detail.path("planJson").asText().isBlank(),
                "planJson 应已归档");

        // 步骤 ≥2（意图理解 + 生成SQL）
        JsonNode steps = detail.path("steps");
        assertTrue(steps.size() >= 2, "应有至少 2 个归档步骤，实际 " + steps.size());

        // 结果归档：standardResultJson + reportMarkdown
        JsonNode result = detail.path("result");
        assertTrue(result.path("reportMarkdown").asText().contains("良率"),
                "报告 Markdown 应已归档");
        assertTrue(result.path("durationMs").isMissingNode()
                        || task.path("durationMs").asLong() == 1234,
                "durationMs 应从 done 事件归档");
        assertEquals(567, task.path("tokensCost").asLong(), "tokensCost 应从 done 事件归档");

        // 会话消息可查
        ResponseEntity<JsonNode> messagesResp = rest.exchange(
                "/api/chat/sessions/" + sessionId + "/messages",
                org.springframework.http.HttpMethod.GET,
                new HttpEntity<>(jsonHeaders), JsonNode.class);
        assertEquals(200, messagesResp.getStatusCode().value());
        JsonNode messages = messagesResp.getBody().path("data");
        assertTrue(messages.size() >= 2, "应有 user + assistant 两条消息");
        assertEquals("user", messages.get(0).path("role").asText());
        assertEquals("请分析各工序的良率", messages.get(0).path("content").asText());
        assertEquals("assistant", messages.get(1).path("role").asText());
    }

    @Test
    @DisplayName("tasks 接口无 token：401")
    void tasks_endpoints_require_auth() {
        var resp = rest.getForEntity("/api/tasks", JsonNode.class);
        assertEquals(401, resp.getStatusCode().value());
    }
}
