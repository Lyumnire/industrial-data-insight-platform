// AI-assisted
package com.a07.server.auth;

import io.jsonwebtoken.ExpiredJwtException;
import io.jsonwebtoken.JwtException;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

/** JwtService 单元测试：签发/解析往返、过期拒绝、篡改拒绝（不依赖 Spring 上下文）。 */
class JwtServiceTests {

    private static final String TEST_SECRET = "unit-test-secret-not-a-production-credential";

    @Test
    @DisplayName("签发后可解析出 subject 与 role 声明")
    void issue_then_parse_roundtrip() {
        JwtService service = new JwtService(TEST_SECRET, 2);
        String token = service.issue("admin", "admin");

        var claims = service.parse(token);

        assertEquals("admin", claims.getSubject());
        assertEquals("admin", claims.get(JwtService.CLAIM_ROLE, String.class));
    }

    @Test
    @DisplayName("过期 token 解析被拒绝")
    void expired_token_rejected() {
        // expire-hours=-1：签发即过期
        JwtService service = new JwtService(TEST_SECRET, -1);
        String token = service.issue("admin", "admin");

        assertThrows(ExpiredJwtException.class, () -> service.parse(token));
    }

    @Test
    @DisplayName("被篡改的 token 解析被拒绝")
    void tampered_token_rejected() {
        JwtService service = new JwtService(TEST_SECRET, 2);
        String token = service.issue("admin", "admin");
        String tampered = token.substring(0, token.length() - 3) + "xyz";
        assertNotEquals(token, tampered);

        assertThrows(JwtException.class, () -> service.parse(tampered));
    }

    @Test
    @DisplayName("未配置密钥时使用临时随机密钥，同一实例内仍可自洽验签")
    void blank_secret_falls_back_to_ephemeral_key() {
        JwtService service = new JwtService("  ", 2);
        String token = service.issue("user", "user");

        var claims = assertDoesNotThrow(() -> service.parse(token));
        assertEquals("user", claims.getSubject());
    }
}
