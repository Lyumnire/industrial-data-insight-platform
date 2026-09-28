// AI-assisted
package com.a07.server.metadata;

import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import com.a07.server.common.ApiResult;

/**
 * 建模页数据表目录（BUG-024 / T-029c）。
 *
 * <p>契约（a07-web {@code http.ts fetchCatalogTables}）：
 * 前端接受裸 {@code string[]}、{@code {data: string[]}} 或 {@code {tables: string[]}}；
 * 本接口统一 {@link ApiResult} 形态，{@code data} 为表名列表。</p>
 *
 * <p>数据来源：平台库 {@code table_metadata}（已注册数据源 JDBC 采集结果，去重排序）。
 * 无已注册表时返回 200 + 空数组，前端降级为示例表并标注；
 * 查询失败返回 503 可读错误（非裸 500），便于诊断。</p>
 */
@RestController
@RequestMapping("/api/catalog")
public class CatalogController {

    private static final Logger log = LoggerFactory.getLogger(CatalogController.class);

    private final MetadataService metadataService;

    public CatalogController(MetadataService metadataService) {
        this.metadataService = metadataService;
    }

    @GetMapping("/tables")
    public ApiResult<List<String>> listTables() {
        try {
            List<String> tables = metadataService.listCatalogTableNames();
            return ApiResult.ok(tables);
        } catch (ResponseStatusException e) {
            throw e;
        } catch (Exception e) {
            log.error("catalog_tables_failed type={} reason={}",
                    e.getClass().getSimpleName(), e.getMessage(), e);
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,
                    "元数据表清单暂不可用: " + e.getMessage());
        }
    }
}
