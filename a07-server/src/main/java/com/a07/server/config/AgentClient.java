// AI-assisted
package com.a07.server.config;

import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;

import com.a07.server.chat.AgentAnalyzeRequest;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * Agent 引擎客户端（docs/03 §3.2 S4「Agent 代理」）。
 * 职责仅两件事：向 POST /api/agent/analyze 发起请求、取回引擎原始响应。
 * 透传层不解析、不改写 SSE 事件内容（契约纪律）；异常显式上抛（红线 R8）。
 *
 * <p>实现说明（2026-09-19 T8 联调修复）：原 WebClient(toEntityFlux) 流式方案在真实
 * LLM 长间隔流下 ~7s 即抛 ReadTimeoutException 断流（responseTimeout/ReadTimeoutHandler
 * 在流式响应上的语义与预期不符），改为 JDK HttpClient + InputStream 阻塞泵，行为完全可推理：
 * send() 在响应头到达时返回（受 header-wait 约束），body 由调用方逐块搬运。
 * 代价是暂无逐读空闲超时（引擎为本地可信服务，P2 如需再引入专用空闲检测）。</p>
 */
@Component
public class AgentClient {

    private static final Logger log = LoggerFactory.getLogger(AgentClient.class);

    /** 引擎唯一入口（docs/03 §3.3 A1）。 */
    public static final String ANALYZE_PATH = "/api/agent/analyze";

    /** 引擎建模直调入口（docs/03 §3.3 A7；BUG-021）。 */
    public static final String ML_RUN_PATH = "/api/agent/ml/run";

    /** 引擎原始响应：状态码 / Content-Type / body 字节流（未解析未改写，调用方负责关闭）。 */
    public record UpstreamResponse(int status, String contentType, InputStream body) {
    }

    /** 引擎 JSON 响应：状态码 / Content-Type / body 字节（未解析未改写）。 */
    public record JsonUpstreamResponse(int status, String contentType, byte[] body) {
    }

    private final HttpClient httpClient;
    private final AgentProperties props;
    private final ObjectMapper objectMapper;

    public AgentClient(AgentProperties props, ObjectMapper objectMapper) {
        this.props = props;
        this.objectMapper = objectMapper;
        this.httpClient = HttpClient.newBuilder()
                // 强制 HTTP/1.1：JDK HttpClient 默认对明文连接发 h2c 升级头，uvicorn 不支持会丢弃请求体（422 body missing）
                .version(java.net.http.HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(props.getConnectTimeoutSeconds()))
                .build();
    }

    /**
     * 建立到引擎的 SSE 连接并阻塞等待响应头（body 流交给调用方字节级搬运）。
     *
     * @throws IOException          连接被拒 / 等待响应头超时等引擎不可达场景
     * @throws InterruptedException 调用线程被中断
     */
    public UpstreamResponse openAnalyzeStream(AgentAnalyzeRequest request)
            throws IOException, InterruptedException {
        log.info("engine_analyze_begin sessionId={} messageId={}", request.sessionId(), request.messageId());
        HttpRequest httpRequest = HttpRequest.newBuilder()
                .uri(URI.create(props.getBaseUrl() + ANALYZE_PATH))
                .timeout(Duration.ofSeconds(props.getHeaderWaitSeconds()))
                .header("Content-Type", MediaType.APPLICATION_JSON_VALUE)
                .header("Accept", MediaType.TEXT_EVENT_STREAM_VALUE)
                .POST(HttpRequest.BodyPublishers.ofString(
                        objectMapper.writeValueAsString(request), java.nio.charset.StandardCharsets.UTF_8))
                .build();
        HttpResponse<InputStream> resp =
                httpClient.send(httpRequest, HttpResponse.BodyHandlers.ofInputStream());
        String contentType = resp.headers().firstValue("Content-Type").orElse(MediaType.TEXT_EVENT_STREAM_VALUE);
        return new UpstreamResponse(resp.statusCode(), contentType, resp.body());
    }

    /**
     * 向引擎 POST {@link #ML_RUN_PATH} 转发建模 JSON（字节级透传，不解析不改写）。
     * 超时预算独立于 SSE header-wait：建模训练可能显著长于流式首包（红线 R8）。
     *
     * @throws IOException          连接被拒 / 等待响应超时等引擎不可达场景
     * @throws InterruptedException 调用线程被中断
     */
    public JsonUpstreamResponse postMlRun(byte[] jsonBody) throws IOException, InterruptedException {
        log.info("engine_ml_run_begin bytes={}", jsonBody == null ? 0 : jsonBody.length);
        byte[] body = (jsonBody == null || jsonBody.length == 0)
                ? "{}".getBytes(java.nio.charset.StandardCharsets.UTF_8)
                : jsonBody;
        HttpRequest httpRequest = HttpRequest.newBuilder()
                .uri(URI.create(props.getBaseUrl() + ML_RUN_PATH))
                .timeout(Duration.ofSeconds(props.getMlTimeoutSeconds()))
                .header("Content-Type", MediaType.APPLICATION_JSON_VALUE)
                .header("Accept", MediaType.APPLICATION_JSON_VALUE)
                .POST(HttpRequest.BodyPublishers.ofByteArray(body))
                .build();
        HttpResponse<byte[]> resp =
                httpClient.send(httpRequest, HttpResponse.BodyHandlers.ofByteArray());
        String contentType = resp.headers().firstValue("Content-Type")
                .orElse(MediaType.APPLICATION_JSON_VALUE);
        log.info("engine_ml_run_end status={}", resp.statusCode());
        byte[] responseBody = resp.body() == null ? new byte[0] : resp.body();
        return new JsonUpstreamResponse(resp.statusCode(), contentType, responseBody);
    }
}
