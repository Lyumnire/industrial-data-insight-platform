// AI-assisted
package com.a07.server.metadata;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import com.a07.server.common.PageResult;
import com.a07.server.config.AgentProperties;
import com.a07.server.knowledge.JsonTextUtil;
import com.a07.server.metadata.MetadataDtos.ColumnMetadataResponse;
import com.a07.server.metadata.MetadataDtos.ConnectionTestResult;
import com.a07.server.metadata.MetadataDtos.DataSourceRequest;
import com.a07.server.metadata.MetadataDtos.DataSourceResponse;
import com.a07.server.metadata.MetadataDtos.RefreshResult;
import com.a07.server.metadata.MetadataDtos.RelationshipResponse;
import com.a07.server.metadata.MetadataDtos.TableMetadataResponse;
import com.fasterxml.jackson.databind.ObjectMapper;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;

/**
 * S3 元数据服务（评分点2）：数据源注册/连通测试/JDBC 采集/引擎 reindex 通知。
 * 红线 R3：密码 AES-GCM 加密后入 password_enc，API 不回传密文。
 */
@Service
public class MetadataService {

    private static final Logger log = LoggerFactory.getLogger(MetadataService.class);

    private static final String REINDEX_PATH = "/internal/reindex";

    private final DataSourceMapper dataSourceMapper;
    private final TableMetadataMapper tableMetadataMapper;
    private final ColumnMetadataMapper columnMetadataMapper;
    private final TableRelationshipMapper relationshipMapper;
    private final MetadataCollector collector;
    private final DataSourceCipher cipher;
    private final AgentProperties agentProperties;
    private final HttpClient httpClient;
    private final ObjectMapper objectMapper;

    public MetadataService(DataSourceMapper dataSourceMapper,
                           TableMetadataMapper tableMetadataMapper,
                           ColumnMetadataMapper columnMetadataMapper,
                           TableRelationshipMapper relationshipMapper,
                           MetadataCollector collector,
                           DataSourceCipher cipher,
                           AgentProperties agentProperties,
                           ObjectMapper objectMapper) {
        this.dataSourceMapper = dataSourceMapper;
        this.tableMetadataMapper = tableMetadataMapper;
        this.columnMetadataMapper = columnMetadataMapper;
        this.relationshipMapper = relationshipMapper;
        this.collector = collector;
        this.cipher = cipher;
        this.agentProperties = agentProperties;
        this.objectMapper = objectMapper;
        this.httpClient = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(5))
                .build();
    }

    // ==================== 数据源 ====================

    public PageResult<DataSourceResponse> listDataSources(String status, long page, long size) {
        Page<DataSourceEntity> p = new Page<>(page, size);
        Page<DataSourceEntity> result = dataSourceMapper.selectPage(p,
                new LambdaQueryWrapper<DataSourceEntity>()
                        .eq(status != null && !status.isBlank(), DataSourceEntity::getStatus, status)
                        .orderByAsc(DataSourceEntity::getId));
        return PageResult.of(result.getTotal(), page, size,
                result.getRecords().stream().map(this::toDataSourceResponse).toList());
    }

    public DataSourceResponse getDataSource(Long id) {
        return toDataSourceResponse(requireDataSource(id));
    }

    @Transactional
    public DataSourceResponse createDataSource(DataSourceRequest req) {
        if (req.name() == null || req.name().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "数据源名称不能为空");
        }
        if (req.jdbcUrl() == null || req.jdbcUrl().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "JDBC URL 不能为空");
        }
        DataSourceEntity e = new DataSourceEntity();
        e.setName(req.name());
        e.setDbType(req.dbType() == null ? "mysql" : req.dbType());
        // T-033/BUG-026：MySQL URL 入库前自动补 characterEncoding=UTF-8（已有则不覆盖）
        e.setJdbcUrl(MetadataCollector.ensureMySqlUtf8(req.jdbcUrl()));
        e.setUsername(req.username());
        e.setPasswordEnc(cipher.encrypt(req.password()));
        e.setStatus(req.status() == null ? "active" : req.status());
        e.setDescription(req.description());
        LocalDateTime now = LocalDateTime.now();
        e.setCreatedAt(now);
        e.setUpdatedAt(now);
        dataSourceMapper.insert(e);
        log.info("datasource_created id={} name={}", e.getId(), e.getName());
        return toDataSourceResponse(e);
    }

    @Transactional
    public DataSourceResponse updateDataSource(Long id, DataSourceRequest req) {
        DataSourceEntity e = requireDataSource(id);
        if (req.name() != null) e.setName(req.name());
        if (req.dbType() != null) e.setDbType(req.dbType());
        if (req.jdbcUrl() != null) e.setJdbcUrl(MetadataCollector.ensureMySqlUtf8(req.jdbcUrl()));
        if (req.username() != null) e.setUsername(req.username());
        if (req.password() != null && !req.password().isBlank()) {
            e.setPasswordEnc(cipher.encrypt(req.password()));
        }
        if (req.status() != null) e.setStatus(req.status());
        if (req.description() != null) e.setDescription(req.description());
        e.setUpdatedAt(LocalDateTime.now());
        dataSourceMapper.updateById(e);
        return toDataSourceResponse(e);
    }

    @Transactional
    public void deleteDataSource(Long id) {
        requireDataSource(id);
        // 级联清理采集元数据
        tableMetadataMapper.deleteByDataSourceId(id);
        columnMetadataMapper.deleteByDataSourceId(id);
        relationshipMapper.deleteByDataSourceId(id);
        dataSourceMapper.deleteById(id);
        log.info("datasource_deleted id={}", id);
    }

    /** 按 id 连通测试。 */
    public ConnectionTestResult testDataSource(Long id) {
        DataSourceEntity e = requireDataSource(id);
        String plainPassword = cipher.decrypt(e.getPasswordEnc());
        return collector.testConnection(e, plainPassword);
    }

    /** 用请求体中的连接信息直接测试（不落库）。 */
    public ConnectionTestResult testConnectionInfo(DataSourceRequest req) {
        DataSourceEntity probe = new DataSourceEntity();
        probe.setJdbcUrl(req.jdbcUrl());
        probe.setUsername(req.username());
        probe.setDbType(req.dbType() == null ? "mysql" : req.dbType());
        return collector.testConnection(probe, req.password());
    }

    // ==================== 元数据采集 ====================

    /**
     * 采集指定数据源的元数据：覆盖写（先删旧再插新），完成后通知引擎 reindex。
     * reindex 失败仅记日志，不阻断采集响应。
     */
    @Transactional
    public RefreshResult refreshDataSource(Long id) {
        DataSourceEntity ds = requireDataSource(id);
        String plainPassword = cipher.decrypt(ds.getPasswordEnc());

        MetadataCollector.CollectionResult result;
        try {
            result = collector.collect(ds, plainPassword);
        } catch (Exception e) {
            log.error("metadata_refresh_failed dataSourceId={} reason={}", id, e.getMessage());
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                    "元数据采集失败: " + e.getMessage());
        }

        // 覆盖写：先删旧记录
        tableMetadataMapper.deleteByDataSourceId(id);
        columnMetadataMapper.deleteByDataSourceId(id);
        relationshipMapper.deleteByDataSourceId(id);

        // 插入新记录
        for (TableMetadataEntity t : result.tables()) {
            tableMetadataMapper.insert(t);
        }
        for (ColumnMetadataEntity c : result.columns()) {
            columnMetadataMapper.insert(c);
        }
        for (TableRelationshipEntity r : result.relationships()) {
            relationshipMapper.insert(r);
        }

        boolean reindexNotified = notifyEngineReindex();
        String msg = reindexNotified ? "采集完成，引擎索引已通知"
                : "采集完成，引擎 reindex 通知失败（不影响采集结果）";
        log.info("metadata_refresh_done dataSourceId={} tables={} columns={} relations={} reindex={}",
                id, result.tables().size(), result.columns().size(),
                result.relationships().size(), reindexNotified);
        return new RefreshResult(result.tables().size(), result.columns().size(),
                result.relationships().size(), reindexNotified, msg);
    }

    /** 直接触发引擎 reindex（不采集）。 */
    public boolean triggerReindex() {
        return notifyEngineReindex();
    }

    // ==================== 元数据查询 ====================

    public PageResult<TableMetadataResponse> listTables(Long dataSourceId, String tableName,
                                                        long page, long size) {
        Page<TableMetadataEntity> p = new Page<>(page, size);
        Page<TableMetadataEntity> result = tableMetadataMapper.selectPage(p,
                new LambdaQueryWrapper<TableMetadataEntity>()
                        .eq(dataSourceId != null, TableMetadataEntity::getDataSourceId, dataSourceId)
                        .like(tableName != null && !tableName.isBlank(),
                                TableMetadataEntity::getTableName, tableName)
                        .orderByAsc(TableMetadataEntity::getTableName));
        return PageResult.of(result.getTotal(), page, size,
                result.getRecords().stream().map(this::toTableResponse).toList());
    }

    /**
     * 建模页目录表名（BUG-024 / GET /api/catalog/tables）。
     * 读 table_metadata 全量表名，去重 + 升序；无注册表返回空列表（前端可降级示例）。
     */
    public List<String> listCatalogTableNames() {
        List<TableMetadataEntity> rows = tableMetadataMapper.selectList(
                new LambdaQueryWrapper<TableMetadataEntity>()
                        .select(TableMetadataEntity::getTableName)
                        .orderByAsc(TableMetadataEntity::getTableName));
        return rows.stream()
                .map(TableMetadataEntity::getTableName)
                .filter(name -> name != null && !name.isBlank())
                .distinct()
                .sorted()
                .toList();
    }

    public PageResult<ColumnMetadataResponse> listColumns(Long dataSourceId, String tableName,
                                                          long page, long size) {
        Page<ColumnMetadataEntity> p = new Page<>(page, size);
        Page<ColumnMetadataEntity> result = columnMetadataMapper.selectPage(p,
                new LambdaQueryWrapper<ColumnMetadataEntity>()
                        .eq(dataSourceId != null, ColumnMetadataEntity::getDataSourceId, dataSourceId)
                        .eq(tableName != null && !tableName.isBlank(),
                                ColumnMetadataEntity::getTableName, tableName)
                        .orderByAsc(ColumnMetadataEntity::getTableName)
                        .orderByAsc(ColumnMetadataEntity::getOrdinal));
        return PageResult.of(result.getTotal(), page, size,
                result.getRecords().stream().map(this::toColumnResponse).toList());
    }

    public List<RelationshipResponse> listRelationships(Long dataSourceId) {
        List<TableRelationshipEntity> list = relationshipMapper.selectList(
                new LambdaQueryWrapper<TableRelationshipEntity>()
                        .eq(dataSourceId != null, TableRelationshipEntity::getDataSourceId, dataSourceId)
                        .orderByAsc(TableRelationshipEntity::getSourceTable));
        return list.stream().map(this::toRelationshipResponse).toList();
    }

    // ==================== 引擎 reindex ====================

    /**
     * 调用引擎 POST /internal/reindex。失败记日志返回 false，不阻断上层调用。
     */
    private boolean notifyEngineReindex() {
        String url = agentProperties.getBaseUrl() + REINDEX_PATH;
        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(url))
                    .timeout(Duration.ofSeconds(10))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString("{}"))
                    .build();
            HttpResponse<String> resp = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            boolean ok = resp.statusCode() < 400;
            if (!ok) {
                log.warn("engine_reindex_non_2xx url={} status={} body={}", url, resp.statusCode(), resp.body());
            } else {
                log.info("engine_reindex_ok url={}", url);
            }
            return ok;
        } catch (Exception e) {
            log.warn("engine_reindex_failed url={} reason={}", url, e.getMessage());
            return false;
        }
    }

    // ==================== 私有工具 ====================

    private DataSourceEntity requireDataSource(Long id) {
        DataSourceEntity e = dataSourceMapper.selectById(id);
        if (e == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "数据源不存在: " + id);
        return e;
    }

    private DataSourceResponse toDataSourceResponse(DataSourceEntity e) {
        // 不回传 passwordEnc（红线 R3）
        return new DataSourceResponse(e.getId(), e.getName(), e.getDbType(), e.getJdbcUrl(),
                e.getUsername(), e.getStatus(), e.getDescription(),
                e.getCreatedAt(), e.getUpdatedAt());
    }

    private TableMetadataResponse toTableResponse(TableMetadataEntity e) {
        return new TableMetadataResponse(e.getId(), e.getDataSourceId(), e.getTableName(),
                e.getTableComment(), e.getTableType(), e.getRowCount(), e.getCollectedAt());
    }

    private ColumnMetadataResponse toColumnResponse(ColumnMetadataEntity e) {
        return new ColumnMetadataResponse(e.getId(), e.getDataSourceId(), e.getTableName(),
                e.getColumnName(), e.getOrdinal(), e.getDataType(), e.getNullable(),
                e.getPrimaryKey(), e.getColumnComment(),
                JsonTextUtil.parseList(e.getSampleValues()));
    }

    private RelationshipResponse toRelationshipResponse(TableRelationshipEntity e) {
        return new RelationshipResponse(e.getId(), e.getDataSourceId(), e.getSourceTable(),
                e.getSourceColumn(), e.getTargetTable(), e.getTargetColumn(), e.getRelationType());
    }
}
