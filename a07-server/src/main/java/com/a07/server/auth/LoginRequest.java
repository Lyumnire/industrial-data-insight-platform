// AI-assisted
package com.a07.server.auth;

import jakarta.validation.constraints.NotBlank;

/**
 * 登录请求体：POST /api/auth/login。
 */
public record LoginRequest(

        @NotBlank(message = "用户名不能为空") String username,

        @NotBlank(message = "密码不能为空") String password) {
}
