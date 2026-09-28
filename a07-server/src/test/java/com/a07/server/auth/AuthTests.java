// AI-assisted
package com.a07.server.auth;

import java.nio.charset.StandardCharsets;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.test.web.servlet.MockMvc;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 登录与安全基线测试（工单验收：成功 200 发 token、错密码 401；H2 内存库 + Flyway 基线）。
 * 用 MockMvc 走完整过滤器链：避免 JDK HttpURLConnection 在 Windows 上对 401 的透明认证重试干扰。
 */
@SpringBootTest
@AutoConfigureMockMvc
class AuthTests {

    @Autowired
    private MockMvc mvc;

    @Autowired
    private UserMapper userMapper;

    @Autowired
    private PasswordEncoder passwordEncoder;

    @Autowired
    private JwtService jwtService;

    private static final String LOGIN_BODY = "{\"username\":\"admin\",\"password\":\"admin123\"}";

    @Test
    @DisplayName("登录成功：200，返回非空 token 与角色 admin")
    void login_success_returns_token_and_role() throws Exception {
        String body = mvc.perform(post("/api/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(LOGIN_BODY))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.token").isNotEmpty())
                .andExpect(jsonPath("$.data.role").value("admin"))
                .andReturn().getResponse().getContentAsString(StandardCharsets.UTF_8);

        // 提取 token 验证内容自洽：可被本服务验签且声明正确
        String token = com.jayway.jsonpath.JsonPath.read(body, "$.data.token");
        var claims = jwtService.parse(token);
        assertEquals("admin", claims.getSubject());
        assertEquals("admin", claims.get(JwtService.CLAIM_ROLE, String.class));
    }

    @Test
    @DisplayName("错密码：401")
    void login_wrong_password_returns_401() throws Exception {
        mvc.perform(post("/api/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"admin\",\"password\":\"wrong-password\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value(401));
    }

    @Test
    @DisplayName("不存在用户：401（与错密码同响应，防用户名枚举）")
    void login_unknown_user_returns_401() throws Exception {
        mvc.perform(post("/api/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"no-such-user\",\"password\":\"whatever\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value(401));
    }

    @Test
    @DisplayName("空字段：400")
    void login_blank_fields_returns_400() throws Exception {
        mvc.perform(post("/api/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"\",\"password\":\"\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value(400));
    }

    @Test
    @DisplayName("受保护接口：无 token 与伪造 token 均 401")
    void protected_endpoint_without_valid_token_returns_401() throws Exception {
        mvc.perform(post("/api/chat/analyze")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"question\":\"请分析各工序的良率\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value(401));

        mvc.perform(post("/api/chat/analyze")
                        .contentType(MediaType.APPLICATION_JSON)
                        .header("Authorization", "Bearer not-a-real-jwt")
                        .content("{\"question\":\"请分析各工序的良率\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value(401));
    }

    @Test
    @DisplayName("种子 3 用户存在：角色正确、BCrypt 哈希可验、库中无明文")
    void seed_users_present_and_bcrypt_matches() {
        String[][] expected = {
                {"admin", "admin123", "admin"},
                {"dm", "dm123456", "dm"},
                {"user", "user123456", "user"},
        };
        for (String[] row : expected) {
            UserEntity user = userMapper.selectOne(new LambdaQueryWrapper<UserEntity>()
                    .eq(UserEntity::getUsername, row[0]));
            assertNotNull(user, "缺少种子用户 " + row[0]);
            assertEquals(row[2], user.getRole(), row[0] + " 角色不符");
            assertTrue(passwordEncoder.matches(row[1], user.getPasswordHash()),
                    row[0] + " 口令哈希校验失败");
            assertNotEquals(row[1], user.getPasswordHash(), row[0] + " 疑似明文入库（红线 R3）");
            assertTrue(user.getPasswordHash().startsWith("$2"), "密码列应为 BCrypt 哈希");
        }
    }

    @Test
    @DisplayName("用错误密钥签发的 token 无法通过本服务验签（跨密钥伪造）")
    void token_signed_with_other_secret_rejected() {
        // 用与测试配置（application.yml）不同的密钥签发一个结构合法的 token
        JwtService foreign = new JwtService("another-secret-entirely-different", 2);
        String forged = foreign.issue("admin", "admin");

        assertThrows(io.jsonwebtoken.JwtException.class, () -> jwtService.parse(forged));
    }
}
