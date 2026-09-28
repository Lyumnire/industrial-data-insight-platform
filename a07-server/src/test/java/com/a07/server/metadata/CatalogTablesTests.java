// AI-assisted
package com.a07.server.metadata;

import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * BUG-024 / T-029c：GET /api/catalog/tables 契约。
 * 前端 fetchCatalogTables 读 data 为 string[]；本接口须 200 可读，失败 503 可读错误，不再 500。
 * 数据来源 table_metadata（已注册数据源采集结果）。
 */
@SpringBootTest
@AutoConfigureMockMvc
class CatalogTablesTests {

    private static final ObjectMapper OM = new ObjectMapper();

    @Autowired
    private MockMvc mvc;

    @Autowired
    private JdbcTemplate jdbc;

    private String loginAsAdmin() throws Exception {
        MvcResult result = mvc.perform(post("/api/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"admin\",\"password\":\"admin123\"}"))
                .andExpect(status().isOk())
                .andReturn();
        JsonNode body = OM.readTree(result.getResponse().getContentAsString(StandardCharsets.UTF_8));
        return body.path("data").path("token").asText();
    }

    @Test
    @DisplayName("catalog/tables 无 token：401")
    void catalog_tables_requires_auth() throws Exception {
        mvc.perform(get("/api/catalog/tables"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    @DisplayName("catalog/tables：200 + data 为 string[]（空注册时可空数组，不 500）")
    void catalog_tables_returns_string_array() throws Exception {
        String token = loginAsAdmin();

        MvcResult result = mvc.perform(get("/api/catalog/tables")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data").isArray())
                .andReturn();

        JsonNode body = OM.readTree(result.getResponse().getContentAsString(StandardCharsets.UTF_8));
        JsonNode data = body.path("data");
        assertTrue(data.isArray(), "data 应为数组: " + data);
        for (JsonNode item : data) {
            assertTrue(item.isTextual(), "表名应为字符串: " + item);
        }
    }

    @Test
    @DisplayName("catalog/tables：读 table_metadata 已注册表名，去重排序")
    void catalog_tables_reads_table_metadata() throws Exception {
        String token = loginAsAdmin();

        // 直插 platform 库 table_metadata（V3 无外键；采集接口依赖源库，本测只验目录读路径）
        jdbc.update("DELETE FROM table_metadata WHERE table_name IN (?, ?, ?)",
                "process_output", "inventory_records", "production_orders");
        jdbc.update("INSERT INTO table_metadata (data_source_id, table_name, table_type, collected_at) "
                        + "VALUES (9901, ?, 'BASE TABLE', CURRENT_TIMESTAMP)",
                "process_output");
        jdbc.update("INSERT INTO table_metadata (data_source_id, table_name, table_type, collected_at) "
                        + "VALUES (9901, ?, 'BASE TABLE', CURRENT_TIMESTAMP)",
                "inventory_records");
        jdbc.update("INSERT INTO table_metadata (data_source_id, table_name, table_type, collected_at) "
                        + "VALUES (9902, ?, 'BASE TABLE', CURRENT_TIMESTAMP)",
                "production_orders");
        // 同名表跨数据源：目录应去重
        jdbc.update("INSERT INTO table_metadata (data_source_id, table_name, table_type, collected_at) "
                        + "VALUES (9902, ?, 'BASE TABLE', CURRENT_TIMESTAMP)",
                "inventory_records");

        try {
            MvcResult result = mvc.perform(get("/api/catalog/tables")
                            .header("Authorization", "Bearer " + token))
                    .andExpect(status().isOk())
                    .andExpect(jsonPath("$.code").value(0))
                    .andReturn();

            JsonNode data = OM.readTree(result.getResponse().getContentAsString(StandardCharsets.UTF_8))
                    .path("data");
            Set<String> tables = new HashSet<>();
            for (JsonNode item : data) {
                tables.add(item.asText());
            }
            assertTrue(tables.contains("process_output"), "应含 process_output: " + tables);
            assertTrue(tables.contains("inventory_records"), "应含 inventory_records: " + tables);
            assertTrue(tables.contains("production_orders"), "应含 production_orders: " + tables);

            long inventoryCount = 0;
            for (JsonNode item : data) {
                if ("inventory_records".equals(item.asText())) {
                    inventoryCount++;
                }
            }
            assertEquals(1, inventoryCount, "同名表应去重，inventory_records 仅出现一次");

            // 排序：全量 data 升序
            String prev = null;
            for (JsonNode item : data) {
                String name = item.asText();
                if (prev != null) {
                    assertTrue(prev.compareTo(name) <= 0,
                            "表名应升序: " + prev + " > " + name);
                }
                prev = name;
            }
        } finally {
            jdbc.update("DELETE FROM table_metadata WHERE table_name IN (?, ?, ?)",
                    "process_output", "inventory_records", "production_orders");
        }
    }
}
