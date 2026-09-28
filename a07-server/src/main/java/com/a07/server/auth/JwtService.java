// AI-assisted
package com.a07.server.auth;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.Duration;
import java.time.Instant;
import java.util.Date;

import javax.crypto.SecretKey;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * JWT 签发与校验（HS256，2h 过期，P1 计划 §Task 6 Step 6.3）。
 * 红线 R3：密钥经环境变量 JWT_SECRET 注入，不硬编码、不入库、不入 Git；
 * 未配置时使用临时随机密钥并告警——进程内可自洽验签，但重启后旧 token 失效，仅限本地开发。
 */
@Service
public class JwtService {

    private static final Logger log = LoggerFactory.getLogger(JwtService.class);

    /** 角色声明键 */
    public static final String CLAIM_ROLE = "role";

    private static final String SHA_256 = "SHA-256";

    /** HS256 密钥最小 256bit */
    private static final int KEY_BYTES = 32;

    private static final SecureRandom RANDOM = new SecureRandom();

    private final SecretKey signingKey;

    private final Duration tokenTtl;

    public JwtService(@Value("${jwt.secret:}") String secret,
                      @Value("${jwt.expire-hours:2}") long expireHours) {
        this.signingKey = Keys.hmacShaKeyFor(deriveKeyBytes(secret));
        this.tokenTtl = Duration.ofHours(expireHours);
    }

    /** 签发 token：sub=用户名，role=角色，2h 过期。 */
    public String issue(String username, String role) {
        Instant now = Instant.now();
        return Jwts.builder()
                .subject(username)
                .claim(CLAIM_ROLE, role)
                .issuedAt(Date.from(now))
                .expiration(Date.from(now.plus(tokenTtl)))
                .signWith(signingKey, Jwts.SIG.HS256)
                .compact();
    }

    /** 校验并解析 token；非法/过期抛 JwtException（过滤器统一转 401）。 */
    public Claims parse(String token) {
        return Jwts.parser()
                .verifyWith(signingKey)
                .build()
                .parseSignedClaims(token)
                .getPayload();
    }

    /** SHA-256 归一化任意长度口令到 32 字节，避免弱密钥；未配置时取临时随机值。 */
    private static byte[] deriveKeyBytes(String secret) {
        if (secret == null || secret.isBlank()) {
            byte[] ephemeral = new byte[KEY_BYTES];
            RANDOM.nextBytes(ephemeral);
            log.warn("JWT_SECRET 未配置：本次启动使用临时随机密钥，重启后已签发 token 将失效（仅限本地开发）");
            return ephemeral;
        }
        try {
            return MessageDigest.getInstance(SHA_256).digest(secret.getBytes(StandardCharsets.UTF_8));
        } catch (NoSuchAlgorithmException e) {
            // JDK 标准算法必然存在，此处仅为通过受检异常（红线 R8：不裸吞）
            throw new IllegalStateException("SHA-256 不可用，无法派生 JWT 密钥", e);
        }
    }
}
