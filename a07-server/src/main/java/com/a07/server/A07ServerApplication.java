// AI-assisted
package com.a07.server;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

/**
 * a07-server 业务底座启动类（docs/03 §3.2）。
 * P1 最小切片：S1 认证权限 + S4 会话与任务的 Agent SSE 代理。
 * 业务逻辑不堆在启动类（红线 R6），仅负责装配与扫描配置属性。
 */
@SpringBootApplication
@ConfigurationPropertiesScan
public class A07ServerApplication {

    public static void main(String[] args) {
        SpringApplication.run(A07ServerApplication.class, args);
    }
}
