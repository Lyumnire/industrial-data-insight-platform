// AI-assisted
package com.a07.server.knowledge;

import java.time.LocalDateTime;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

/**
 * analysis_topics 表实体（V2__knowledge.sql）：分析主题（S2 知识四实体之一）。
 * related_object_ids/related_metric_ids 存关联对象/指标的<b>业务编码</b>（JSON 数组字符串），
 * 跨环境自增 id 不稳定，编码是图接口连边的稳定锚点（偏离工单字段名的字面语义，见工单完成记录）。
 */
@TableName("analysis_topics")
public class AnalysisTopicEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String code;

    private String name;

    private String description;

    /** 业务域：生产/质量/设备/库存 */
    private String domain;

    /** 关联业务对象编码 JSON 数组字符串 */
    private String relatedObjectIds;

    /** 关联业务指标编码 JSON 数组字符串 */
    private String relatedMetricIds;

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

    public String getDescription() {
        return description;
    }

    public void setDescription(String description) {
        this.description = description;
    }

    public String getDomain() {
        return domain;
    }

    public void setDomain(String domain) {
        this.domain = domain;
    }

    public String getRelatedObjectIds() {
        return relatedObjectIds;
    }

    public void setRelatedObjectIds(String relatedObjectIds) {
        this.relatedObjectIds = relatedObjectIds;
    }

    public String getRelatedMetricIds() {
        return relatedMetricIds;
    }

    public void setRelatedMetricIds(String relatedMetricIds) {
        this.relatedMetricIds = relatedMetricIds;
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
