// AI-assisted
package com.a07.server.metadata;

import java.util.List;

import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import com.a07.server.common.ApiResult;
import com.a07.server.common.PageResult;
import com.a07.server.metadata.MetadataDtos.ColumnMetadataResponse;
import com.a07.server.metadata.MetadataDtos.ConnectionTestResult;
import com.a07.server.metadata.MetadataDtos.DataSourceRequest;
import com.a07.server.metadata.MetadataDtos.DataSourceResponse;
import com.a07.server.metadata.MetadataDtos.RefreshResult;
import com.a07.server.metadata.MetadataDtos.RelationshipResponse;
import com.a07.server.metadata.MetadataDtos.TableMetadataResponse;

/**
 * S3 元数据 REST 接口（评分点2 + 现场接新表）。
 * 新路径 authenticated；细粒度 RBAC 记遗留。
 */
@RestController
@RequestMapping("/api/metadata")
public class MetadataController {

    private final MetadataService metadataService;

    public MetadataController(MetadataService metadataService) {
        this.metadataService = metadataService;
    }

    // ==================== 数据源 ====================

    @GetMapping("/datasources")
    public ApiResult<PageResult<DataSourceResponse>> listDataSources(
            @RequestParam(required = false) String status,
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size) {
        return ApiResult.ok(metadataService.listDataSources(status, page, size));
    }

    @GetMapping("/datasources/{id}")
    public ApiResult<DataSourceResponse> getDataSource(@PathVariable Long id) {
        return ApiResult.ok(metadataService.getDataSource(id));
    }

    @PostMapping("/datasources")
    public ApiResult<DataSourceResponse> createDataSource(@RequestBody DataSourceRequest request) {
        return ApiResult.ok(metadataService.createDataSource(request));
    }

    @PutMapping("/datasources/{id}")
    public ApiResult<DataSourceResponse> updateDataSource(@PathVariable Long id,
                                                          @RequestBody DataSourceRequest request) {
        return ApiResult.ok(metadataService.updateDataSource(id, request));
    }

    @DeleteMapping("/datasources/{id}")
    public ApiResult<Void> deleteDataSource(@PathVariable Long id) {
        metadataService.deleteDataSource(id);
        return ApiResult.ok(null);
    }

    @PostMapping("/datasources/{id}/test")
    public ApiResult<ConnectionTestResult> testDataSource(@PathVariable Long id) {
        return ApiResult.ok(metadataService.testDataSource(id));
    }

    @PostMapping("/datasources/test")
    public ApiResult<ConnectionTestResult> testConnectionInfo(@RequestBody DataSourceRequest request) {
        return ApiResult.ok(metadataService.testConnectionInfo(request));
    }

    @PostMapping("/datasources/{id}/refresh")
    public ApiResult<RefreshResult> refreshDataSource(@PathVariable Long id) {
        return ApiResult.ok(metadataService.refreshDataSource(id));
    }

    // ==================== 元数据查询 ====================

    @GetMapping("/tables")
    public ApiResult<PageResult<TableMetadataResponse>> listTables(
            @RequestParam(required = false) Long dataSourceId,
            @RequestParam(required = false) String tableName,
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size) {
        return ApiResult.ok(metadataService.listTables(dataSourceId, tableName, page, size));
    }

    @GetMapping("/columns")
    public ApiResult<PageResult<ColumnMetadataResponse>> listColumns(
            @RequestParam(required = false) Long dataSourceId,
            @RequestParam(required = false) String tableName,
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size) {
        return ApiResult.ok(metadataService.listColumns(dataSourceId, tableName, page, size));
    }

    @GetMapping("/relationships")
    public ApiResult<List<RelationshipResponse>> listRelationships(
            @RequestParam(required = false) Long dataSourceId) {
        return ApiResult.ok(metadataService.listRelationships(dataSourceId));
    }

    // ==================== 引擎 reindex ====================

    @PostMapping("/reindex")
    public ApiResult<Boolean> reindex() {
        return ApiResult.ok(metadataService.triggerReindex());
    }
}
