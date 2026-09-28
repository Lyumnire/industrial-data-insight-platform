// AI-assisted
package com.a07.server.auth;

import java.io.IOException;
import java.nio.charset.StandardCharsets;

import com.fasterxml.jackson.databind.ObjectMapper;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.web.AuthenticationEntryPoint;
import org.springframework.stereotype.Component;

import com.a07.server.common.ApiResult;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

/**
 * 未认证访问受保护接口时返回 401 统一 JSON（JWT 模式无登录页可跳转）。
 */
@Component
public class RestAuthenticationEntryPoint implements AuthenticationEntryPoint {

    private static final Logger log = LoggerFactory.getLogger(RestAuthenticationEntryPoint.class);

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static final int HTTP_UNAUTHORIZED = 401;

    @Override
    public void commence(HttpServletRequest request, HttpServletResponse response,
                         AuthenticationException authException) throws IOException {
        log.warn("unauthorized uri={}", request.getRequestURI());
        response.setStatus(HTTP_UNAUTHORIZED);
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        MAPPER.writeValue(response.getWriter(), ApiResult.error(HTTP_UNAUTHORIZED, "未登录或凭证无效"));
    }
}
