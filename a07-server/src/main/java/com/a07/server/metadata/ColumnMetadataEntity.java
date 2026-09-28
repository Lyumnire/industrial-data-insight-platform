// AI-assisted
package com.a07.server.metadata;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

/** column_metadata 表实体（V3）：JDBC 采集的列级元数据，含主键标记与样例值。 */
@TableName("column_metadata")
public class ColumnMetadataEntity {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long dataSourceId;

    private String tableName;

    private String columnName;

    private Integer ordinal;

    private String dataType;

    private String nullable;

    private String primaryKey;

    private String columnComment;

    /** JSON 数组字符串，≤5 个样例值 */
    private String sampleValues;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getDataSourceId() { return dataSourceId; }
    public void setDataSourceId(Long dataSourceId) { this.dataSourceId = dataSourceId; }
    public String getTableName() { return tableName; }
    public void setTableName(String tableName) { this.tableName = tableName; }
    public String getColumnName() { return columnName; }
    public void setColumnName(String columnName) { this.columnName = columnName; }
    public Integer getOrdinal() { return ordinal; }
    public void setOrdinal(Integer ordinal) { this.ordinal = ordinal; }
    public String getDataType() { return dataType; }
    public void setDataType(String dataType) { this.dataType = dataType; }
    public String getNullable() { return nullable; }
    public void setNullable(String nullable) { this.nullable = nullable; }
    public String getPrimaryKey() { return primaryKey; }
    public void setPrimaryKey(String primaryKey) { this.primaryKey = primaryKey; }
    public String getColumnComment() { return columnComment; }
    public void setColumnComment(String columnComment) { this.columnComment = columnComment; }
    public String getSampleValues() { return sampleValues; }
    public void setSampleValues(String sampleValues) { this.sampleValues = sampleValues; }
}
