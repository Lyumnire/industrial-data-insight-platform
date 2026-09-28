// AI-assisted
package com.a07.server.knowledge;

import java.time.LocalDateTime;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

/**
 * business_rules 表实体（V2__knowledge.sql）：业务规则（S2 知识四实体之一）。
 * rule_type 枚举：口径/时间/空值/异常/特殊；applies_to 为指标编码 JSON 数组字符串。
 */
@TableName("business_rules")
public class BusinessRuleEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String code;

    private String name;

    /** 口径/时间/空值/异常/特殊 */
    private String ruleType;

    private String content;

    /** 适用指标编码 JSON 数组字符串（空数组 = 全局规则） */
    private String appliesTo;

    /** active | disabled */
    private String status;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getCode() {
        return code;
    }

    public void setCode(String code) {
        this.code = code;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        this.name = name;
    }

    public String getRuleType() {
        return ruleType;
    }

    public void setRuleType(String ruleType) {
        this.ruleType = ruleType;
    }

    public String getContent() {
        return content;
    }

    public void setContent(String content) {
        this.content = content;
    }

    public String getAppliesTo() {
        return appliesTo;
    }

    public void setAppliesTo(String appliesTo) {
        this.appliesTo = appliesTo;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public LocalDateTime getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(LocalDateTime createdAt) {
        this.createdAt = createdAt;
    }

    public LocalDateTime getUpdatedAt() {
        return updatedAt;
    }

    public void setUpdatedAt(LocalDateTime updatedAt) {
        this.updatedAt = updatedAt;
    }
}
