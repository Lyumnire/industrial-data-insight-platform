// AI-assisted
package com.a07.server.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import com.baomidou.mybatisplus.annotation.DbType;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.PaginationInnerInterceptor;

/**
 * MyBatis-Plus 插件配置：分页拦截器（T-016 S2/S3/S4 列表接口依赖）。
 * 没有此拦截器，selectPage 返回的 total 恒为 0。
 */
@Configuration
public class MybatisPlusConfig {

    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
        PaginationInnerInterceptor pagination = new PaginationInnerInterceptor(DbType.H2);
        pagination.setMaxLimit(500L);
        interceptor.addInnerInterceptor(pagination);
        return interceptor;
    }
}
