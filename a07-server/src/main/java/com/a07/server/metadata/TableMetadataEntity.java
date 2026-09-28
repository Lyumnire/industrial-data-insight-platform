// AI-assisted
package com.a07.server.metadata;

import java.time.LocalDateTime;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

/** table_metadata 表实体（V3）：JDBC 采集的表级元数据，refresh 覆盖写。 */
@TableName("table_metadata")
public class TableMetadataEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long dataSourceId;

    private String tableName;

    private String tableComment;

    private String tableType;

    private Long rowCount;

    private LocalDateTime collectedAt;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getDataSourceId() { return dataSourceId; }
    public void setDataSourceId(Long dataSourceId) { this.dataSourceId = dataSourceId; }
    public String getTableName() { return tableName; }
    public void setTableName(String tableName) { this.tableName = tableName; }
    public String getTableComment() { return tableComment; }
    public void setTableComment(String tableComment) { this.tableComment = tableComment; }
    public String getTableType() { return tableType; }
    public void setTableType(String tableType) { this.tableType = tableType; }
    public Long getRowCount() { return rowCount; }
    public void setRowCount(Long rowCount) { this.rowCount = rowCount; }
    public LocalDateTime getCollectedAt() { return collectedAt; }
    public void setCollectedAt(LocalDateTime collectedAt) { this.collectedAt = collectedAt; }
}
