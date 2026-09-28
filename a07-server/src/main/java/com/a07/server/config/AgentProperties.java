// AI-assisted
package com.a07.server.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Agent 引擎连接配置（docs/03 §3.2 S4 → a07-agent）。
 * 环境相关地址全部经环境变量注入（红线 R3），此处仅声明键与开发默认值。
 */
@ConfigurationProperties(prefix = "agent")
public class AgentProperties {

    /** 引擎根地址，如 http://localhost:8100 */
    private String baseUrl = "http://localhost:8100";

    /** TCP 连接建立超时（秒） */
    private long connectTimeoutSeconds = 5;

    /** 等待引擎响应头的预算（秒）：超过即判引擎不可达，返回 502 */
    private long headerWaitSeconds = 15;

    /** 透传期间空闲读超时（秒）：引擎连续无字节下发则断开（红线 R8） */
    private long readIdleTimeoutSeconds = 120;

    /** 建模直调 POST /api/agent/ml/run 整请求超时（秒）：训练可显著长于 SSE 首包（BUG-021 / 红线 R8） */
    private long mlTimeoutSeconds = 120;

    public String getBaseUrl() {
        return baseUrl;
    }

    public void setBaseUrl(String baseUrl) {
        this.baseUrl = baseUrl;
    }

    public long getConnectTimeoutSeconds() {
        return connectTimeoutSeconds;
    }

    public void setConnectTimeoutSeconds(long connectTimeoutSeconds) {
        this.connectTimeoutSeconds = connectTimeoutSeconds;
    }

    public long getHeaderWaitSeconds() {
        return headerWaitSeconds;
    }

    public void setHeaderWaitSeconds(long headerWaitSeconds) {
        this.headerWaitSeconds = headerWaitSeconds;
    }

    public long getReadIdleTimeoutSeconds() {
        return readIdleTimeoutSeconds;
    }

    public void setReadIdleTimeoutSeconds(long readIdleTimeoutSeconds) {
        this.readIdleTimeoutSeconds = readIdleTimeoutSeconds;
    }

    public long getMlTimeoutSeconds() {
        return mlTimeoutSeconds;
    }

    public void setMlTimeoutSeconds(long mlTimeoutSeconds) {
        this.mlTimeoutSeconds = mlTimeoutSeconds;
    }
}
