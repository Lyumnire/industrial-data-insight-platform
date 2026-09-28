// AI-assisted
package com.a07.server.metadata;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.Base64;

import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * 数据源密码 AES-GCM 加解密（红线 R3：password_enc 禁明文）。
 * 密钥经环境变量 METADATA_CIPHER_KEY 注入；未配置时使用开发默认派生密钥并告警。
 * 密文格式：Base64( IV[12] || ciphertext+tag )。
 */
@Component
public class DataSourceCipher {

    private static final Logger log = LoggerFactory.getLogger(DataSourceCipher.class);

    private static final String ALGORITHM = "AES/GCM/NoPadding";
    private static final int GCM_TAG_BITS = 128;
    private static final int IV_LENGTH = 12;
    private static final int KEY_BYTES = 32;

    private final SecretKeySpec secretKey;

    public DataSourceCipher(@Value("${metadata.cipher.key:}") String cipherKey) {
        this.secretKey = new SecretKeySpec(deriveKey(cipherKey), "AES");
    }

    /** 加密明文密码 → Base64 密文。 */
    public String encrypt(String plainText) {
        if (plainText == null || plainText.isBlank()) {
            return null;
        }
        try {
            byte[] iv = new byte[IV_LENGTH];
            new SecureRandom().nextBytes(iv);
            Cipher cipher = Cipher.getInstance(ALGORITHM);
            cipher.init(Cipher.ENCRYPT_MODE, secretKey, new GCMParameterSpec(GCM_TAG_BITS, iv));
            byte[] encrypted = cipher.doFinal(plainText.getBytes(StandardCharsets.UTF_8));
            byte[] combined = new byte[iv.length + encrypted.length];
            System.arraycopy(iv, 0, combined, 0, iv.length);
            System.arraycopy(encrypted, 0, combined, iv.length, encrypted.length);
            return Base64.getEncoder().encodeToString(combined);
        } catch (Exception e) {
            throw new IllegalStateException("密码加密失败", e);
        }
    }

    /** 解密密文 → 明文密码；密文为空返回 null。 */
    public String decrypt(String cipherText) {
        if (cipherText == null || cipherText.isBlank()) {
            return null;
        }
        try {
            byte[] combined = Base64.getDecoder().decode(cipherText);
            if (combined.length <= IV_LENGTH) {
                throw new IllegalArgumentException("密文长度不足");
            }
            byte[] iv = new byte[IV_LENGTH];
            System.arraycopy(combined, 0, iv, 0, IV_LENGTH);
            byte[] encrypted = new byte[combined.length - IV_LENGTH];
            System.arraycopy(combined, IV_LENGTH, encrypted, 0, encrypted.length);
            Cipher cipher = Cipher.getInstance(ALGORITHM);
            cipher.init(Cipher.DECRYPT_MODE, secretKey, new GCMParameterSpec(GCM_TAG_BITS, iv));
            return new String(cipher.doFinal(encrypted), StandardCharsets.UTF_8);
        } catch (Exception e) {
            throw new IllegalStateException("密码解密失败（密钥是否变更？）", e);
        }
    }

    /** SHA-256 归一化任意长度口令到 32 字节；未配置时使用开发默认值并告警。 */
    private static byte[] deriveKey(String cipherKey) {
        if (cipherKey == null || cipherKey.isBlank()) {
            log.warn("METADATA_CIPHER_KEY 未配置：使用开发默认密钥派生，生产环境必须注入环境变量（红线 R3）");
            cipherKey = "a07-dev-metadata-cipher-key-change-in-production";
        }
        try {
            return MessageDigest.getInstance("SHA-256").digest(cipherKey.getBytes(StandardCharsets.UTF_8));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 不可用，无法派生元数据加密密钥", e);
        }
    }
}
