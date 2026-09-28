// AI-assisted
package com.a07.server.metadata;

import java.time.LocalDateTime;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

/** table_relationships 表实体（V3）：外键采集 + 人工标注预留。 */
@TableName("table_relationships")
public class TableRelationshipEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long dataSourceId;

    private String sourceTable;

    private String sourceColumn;

    private String targetTable;

    private String targetColumn;

    /** fk | manual */
    private String relationType;

    private LocalDateTime createdAt;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getDataSourceId() { return dataSourceId; }
    public void setDataSourceId(Long dataSourceId) { this.dataSourceId = dataSourceId; }
    public String getSourceTable() { return sourceTable; }
    public void setSourceTable(String sourceTable) { this.sourceTable = sourceTable; }
    public String getSourceColumn() { return sourceColumn; }
    public void setSourceColumn(String sourceColumn) { this.sourceColumn = sourceColumn; }
    public String getTargetTable() { return targetTable; }
    public void setTargetTable(String targetTable) { this.targetTable = targetTable; }
    public String getTargetColumn() { return targetColumn; }
    public void setTargetColumn(String targetColumn) { this.targetColumn = targetColumn; }
    public String getRelationType() { return relationType; }
    public void setRelationType(String relationType) { this.relationType = relationType; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
}
