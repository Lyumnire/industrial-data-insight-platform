// AI-assisted
package com.a07.server.common;

/**
 * 统一响应体 {code, message, data}（docs/03 §3.2 对外契约规范）。
 * code=0 表示业务成功；非 0 与 HTTP 状态码保持一致口径。
 */
public record ApiResult<T>(int code, String message, T data) {

    public static <T> ApiResult<T> ok(T data) {
        return new ApiResult<>(0, "ok", data);
    }

    public static ApiResult<Void> error(int code, String message) {
        return new ApiResult<>(code, message, null);
    }
}
