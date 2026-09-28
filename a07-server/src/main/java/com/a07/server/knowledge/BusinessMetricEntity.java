// AI-assisted
package com.a07.server.knowledge;

import java.time.LocalDateTime;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

/**
 * business_metrics 表实体（V2__knowledge.sql）：业务指标口径（S2 知识四实体之一）。
 * source_tables/source_columns 为 JSON 数组字符串（TEXT），对外由 Service 转列表。
 */
@TableName("business_metrics")
public class BusinessMetricEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String code;

    private String name;

    private String description;

    /** 计算公式（可展开的 SQL 片段，如 SUM(qualified_qty)/NULLIF(SUM(produced_qty),0)） */
    private String formulaSql;

    private String unit;

    /** 业务域：生产/质量/设备/库存 */
    private String domain;

    /** 来源表 JSON 数组字符串 */
    private String sourceTables;

    /** 来源字段 JSON 数组字符串 */
    private String sourceColumns;

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

    public String getFormulaSql() {
        return formulaSql;
    }

    public void setFormulaSql(String formulaSql) {
        this.formulaSql = formulaSql;
    }

    public String getUnit() {
        return unit;
    }

    public void setUnit(String unit) {
        this.unit = unit;
    }

    public String getDomain() {
        return domain;
    }

    public void setDomain(String domain) {
        this.domain = domain;
    }

    public String getSourceTables() {
        return sourceTables;
    }

    public void setSourceTables(String sourceTables) {
        this.sourceTables = sourceTables;
    }

    public String getSourceColumns() {
        return sourceColumns;
    }

    public void setSourceColumns(String sourceColumns) {
        this.sourceColumns = sourceColumns;
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
