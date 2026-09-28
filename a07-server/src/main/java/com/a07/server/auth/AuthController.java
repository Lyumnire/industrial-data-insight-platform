// AI-assisted
package com.a07.server.auth;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import com.a07.server.common.ApiResult;

import jakarta.validation.Valid;

/**
 * S1 认证接口（docs/03 §3.2）：POST /api/auth/login，成功发 {token, role}。
 * 失败统一 401"用户名或密码错误"，不区分"用户不存在/密码错误"，避免用户名枚举。
 */
@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private static final Logger log = LoggerFactory.getLogger(AuthController.class);

    private final UserMapper userMapper;
    private final PasswordEncoder passwordEncoder;
    private final JwtService jwtService;

    public AuthController(UserMapper userMapper, PasswordEncoder passwordEncoder, JwtService jwtService) {
        this.userMapper = userMapper;
        this.passwordEncoder = passwordEncoder;
        this.jwtService = jwtService;
    }

    @PostMapping("/login")
    public ApiResult<LoginResponse> login(@Valid @RequestBody LoginRequest request) {
        UserEntity user = userMapper.selectOne(new LambdaQueryWrapper<UserEntity>()
                .eq(UserEntity::getUsername, request.username()));
        if (user == null || !passwordEncoder.matches(request.password(), user.getPasswordHash())) {
            log.warn("login_failed username={}", request.username());
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "用户名或密码错误");
        }
        String token = jwtService.issue(user.getUsername(), user.getRole());
        log.info("login_success username={} role={}", user.getUsername(), user.getRole());
        return ApiResult.ok(new LoginResponse(token, user.getRole()));
    }
}
