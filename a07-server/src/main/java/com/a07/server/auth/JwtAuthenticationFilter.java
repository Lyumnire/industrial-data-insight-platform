// AI-assisted
package com.a07.server.auth;

import java.io.IOException;
import java.util.List;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

/**
 * JWT 过滤器：解析 Authorization: Bearer &lt;jwt&gt; 并注入 SecurityContext。
 * 无效凭证不抛异常也不写响应，仅清空上下文，由 EntryPoint 统一返回 401 JSON（红线 R8）。
 */
@Component
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(JwtAuthenticationFilter.class);

    private static final String BEARER_PREFIX = "Bearer ";

    private final JwtService jwtService;

    public JwtAuthenticationFilter(JwtService jwtService) {
        this.jwtService = jwtService;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String header = request.getHeader(HttpHeaders.AUTHORIZATION);
        if (header != null && header.startsWith(BEARER_PREFIX)) {
            try {
                Claims claims = jwtService.parse(header.substring(BEARER_PREFIX.length()));
                Object roleClaim = claims.get(JwtService.CLAIM_ROLE);
                List<SimpleGrantedAuthority> authorities = roleClaim == null
                        ? List.of()
                        : List.of(new SimpleGrantedAuthority("ROLE_" + roleClaim));
                UsernamePasswordAuthenticationToken authentication =
                        new UsernamePasswordAuthenticationToken(claims.getSubject(), null, authorities);
                SecurityContextHolder.getContext().setAuthentication(authentication);
            } catch (JwtException | IllegalArgumentException e) {
                log.warn("jwt_rejected uri={} reason={}", request.getRequestURI(), e.getMessage());
                SecurityContextHolder.clearContext();
            }
        }
        chain.doFilter(request, response);
    }
}
