// AI-assisted
package com.a07.server.common;

import java.util.List;

/**
 * 分页响应载荷（docs/03 §3.2 统一响应体内的 data 结构）。
 * 不直接暴露 MyBatis-Plus 的 Page 对象，保持对外契约与持久层解耦。
 */
public record PageResult<T>(long total, long page, long size, List<T> records) {

    public static <T> PageResult<T> of(long total, long page, long size, List<T> records) {
        return new PageResult<>(total, page, size, records);
    }
}
