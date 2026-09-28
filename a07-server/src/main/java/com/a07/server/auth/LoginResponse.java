// AI-assisted
package com.a07.server.auth;

/** 登录响应体：JWT 与角色。 */
public record LoginResponse(String token, String role) {
}
