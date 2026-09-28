// AI-assisted
package com.a07.server.config;

import java.util.List;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

/**
 * CORS 配置：P1 仅放行本机前端开发源（a07-web Vite 默认 5173）。
 * P2 部署时按实际域名收口（工单变更申请流程）。
 */
@Configuration
public class CorsConfig {

    private static final List<String> ALLOWED_ORIGINS = List.of("http://localhost:5173");

    private static final long PREFLIGHT_MAX_AGE_SECONDS = 3600L;

    @Bean
    public CorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration config = new CorsConfiguration();
        config.setAllowedOrigins(ALLOWED_ORIGINS);
        config.setAllowedMethods(List.of("GET", "POST", "PUT", "DELETE", "OPTIONS"));
        config.setAllowedHeaders(List.of("*"));
        config.setMaxAge(PREFLIGHT_MAX_AGE_SECONDS);
        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", config);
        return source;
    }
}
