// AI-assisted
package com.a07.server.common;

import java.util.stream.Collectors;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.HttpMediaTypeNotAcceptableException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.server.ResponseStatusException;

/**
 * 统一异常出口（红线 R8）：所有未在控制器内处理的异常都映射为 {code, message} 结构，并输出结构化日志。
 *
 * <p>关键点：统一响应必须显式声明 {@code Content-Type: application/json}——
 * 客户端（尤其 SSE 透传端）可能只 Accept: text/event-stream，若走默认内容协商，
 * Jackson 无法按该类型渲染 JSON，异常处理会退化为无响应体的 sendError。</p>
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    /** @Valid 参数校验失败：400，明细附字段错误，便于前端定位。 */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ApiResult<Void>> handleValidation(MethodArgumentNotValidException e) {
        String detail = e.getBindingResult().getFieldErrors().stream()
                .map(f -> f.getField() + ": " + f.getDefaultMessage())
                .collect(Collectors.joining("; "));
        log.warn("bad_request_validation detail={}", detail);
        return json(HttpStatus.BAD_REQUEST, "参数校验失败: " + detail);
    }

    /** 请求体不是合法 JSON：400。 */
    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<ApiResult<Void>> handleUnreadable(HttpMessageNotReadableException e) {
        log.warn("bad_request_unreadable reason={}", e.getMessage());
        return json(HttpStatus.BAD_REQUEST, "请求体格式错误");
    }

    /** Accept 与接口 produces 不匹配：406（如 /api/chat/analyze 未声明 Accept: text/event-stream）。 */
    @ExceptionHandler(HttpMediaTypeNotAcceptableException.class)
    public ResponseEntity<ApiResult<Void>> handleNotAcceptable(HttpMediaTypeNotAcceptableException e) {
        log.warn("not_acceptable reason={}", e.getMessage());
        return json(HttpStatus.NOT_ACCEPTABLE,
                "不接受该响应类型：/api/chat/analyze 需 Accept: text/event-stream");
    }

    /** HTTP 方法不支持：405。 */
    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    public ResponseEntity<ApiResult<Void>> handleMethodNotSupported(HttpRequestMethodNotSupportedException e) {
        log.warn("method_not_allowed method={}", e.getMethod());
        return json(HttpStatus.METHOD_NOT_ALLOWED, "不支持的请求方法");
    }

    /** 显式声明的业务状态异常：按其状态码返回。 */
    @ExceptionHandler(ResponseStatusException.class)
    public ResponseEntity<ApiResult<Void>> handleStatus(ResponseStatusException e) {
        int code = e.getStatusCode().value();
        String message = e.getReason() == null ? "请求失败" : e.getReason();
        log.warn("status_exception code={} message={}", code, message);
        return json(HttpStatus.resolve(code) == null ? HttpStatus.INTERNAL_SERVER_ERROR
                : HttpStatus.resolve(code), message);
    }

    /** 未知路径（Spring 6.x 把未匹配路由当静态资源查找后抛出）：404 而非落入兜底 500（BUG-027）。 */
    @ExceptionHandler(org.springframework.web.servlet.resource.NoResourceFoundException.class)
    public ResponseEntity<ApiResult<Void>> handleNoResource(
            org.springframework.web.servlet.resource.NoResourceFoundException e) {
        log.warn("not_found path={}", e.getResourcePath());
        return json(HttpStatus.NOT_FOUND, "接口不存在: " + e.getResourcePath());
    }

    /** 兜底：未知异常一律 500 并记录堆栈，对外不泄漏内部细节。 */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiResult<Void>> handleUnknown(Exception e) {
        log.error("internal_error type={}", e.getClass().getName(), e);
        return json(HttpStatus.INTERNAL_SERVER_ERROR, "服务器内部错误，请稍后重试");
    }

    /** 统一出口：显式 application/json，绕过 Accept 协商（SSE 客户端也能收到错误体）。 */
    private static ResponseEntity<ApiResult<Void>> json(HttpStatus status, String message) {
        return ResponseEntity.status(status)
                .contentType(MediaType.APPLICATION_JSON)
                .body(ApiResult.error(status.value(), message));
    }
}
