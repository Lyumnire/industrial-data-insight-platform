// AI-assisted
package com.a07.server.metadata;

import java.time.LocalDateTime;
import java.util.List;

import com.fasterxml.jackson.annotation.JsonInclude;

/** S3 元数据对外 DTO。 */
public final class MetadataDtos {

    private MetadataDtos() {
    }

    // ---------- 数据源 ----------

    /** 注册/更新请求：password 为明文（仅传输，不入库），入库时 AES-GCM 加密。 */
    public record DataSourceRequest(String name, String dbType, String jdbcUrl,
                                    String username, String password,
                                    String status, String description) {
    }

    /** 数据源响应：不回传 passwordEnc / password（红线 R3）。 */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record DataSourceResponse(Long id, String name, String dbType, String jdbcUrl,
                                     String username, String status, String description,
                                     LocalDateTime createdAt, LocalDateTime updatedAt) {
    }

    /** 连通测试结果。 */
    public record ConnectionTestResult(boolean connected, String message, Integer tableCount) {
    }

    // ---------- 表/列元数据 ----------

    public record TableMetadataResponse(Long id, Long dataSourceId, String tableName,
                                        String tableComment, String tableType,
                                        Long rowCount, LocalDateTime collectedAt) {
    }

    public record ColumnMetadataResponse(Long id, Long dataSourceId, String tableName,
                                         String columnName, Integer ordinal, String dataType,
                                         String nullable, String primaryKey,
                                         String columnComment, List<String> sampleValues) {
    }

    public record RelationshipResponse(Long id, Long dataSourceId, String sourceTable,
                                       String sourceColumn, String targetTable,
                                       String targetColumn, String relationType) {
    }

    // ---------- 采集结果 ----------

    /** refresh 采集结果摘要。 */
    public record RefreshResult(long tableCount, long columnCount, long relationshipCount,
                                boolean reindexNotified, String message) {
    }
}
