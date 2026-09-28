// AI-assisted
package com.a07.server.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

import com.a07.server.auth.JwtAuthenticationFilter;
import com.a07.server.auth.RestAuthenticationEntryPoint;

/**
 * Spring Security 配置（P1 计划 §Task 6 Step 6.3；T-016 更新）：
 * - /api/auth/** 放行（登录入口），其余一律 authenticated（含 T-016 新增
 *   /api/knowledge/**、/api/metadata/**、/api/chat/sessions、/api/tasks/**）；
 * - 无状态会话 + 关闭 CSRF（JWT 模式）；
 * - 未认证统一 401 JSON（RestAuthenticationEntryPoint，红线 R8 统一异常体）。
 * - 细粒度 RBAC（admin/dm/user 分权）记遗留，当前登录即可访问全部业务接口。
 */
@Configuration
@EnableWebSecurity
public class SecurityConfig {

    /** 无需登录即可访问的路径；/error 放行以避免真实错误被 401 掩盖。 */
    public static final String[] PUBLIC_PATHS = {"/api/auth/**", "/error"};

    private final JwtAuthenticationFilter jwtAuthenticationFilter;
    private final RestAuthenticationEntryPoint authenticationEntryPoint;

    public SecurityConfig(JwtAuthenticationFilter jwtAuthenticationFilter,
                          RestAuthenticationEntryPoint authenticationEntryPoint) {
        this.jwtAuthenticationFilter = jwtAuthenticationFilter;
        this.authenticationEntryPoint = authenticationEntryPoint;
    }

    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http.csrf(AbstractHttpConfigurer::disable)
                .cors(Customizer.withDefaults())
                .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers(PUBLIC_PATHS).permitAll()
                        .anyRequest().authenticated())
                .exceptionHandling(e -> e.authenticationEntryPoint(authenticationEntryPoint))
                .addFilterBefore(jwtAuthenticationFilter, UsernamePasswordAuthenticationFilter.class)
                .formLogin(AbstractHttpConfigurer::disable)
                .httpBasic(AbstractHttpConfigurer::disable);
        return http.build();
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }
}
