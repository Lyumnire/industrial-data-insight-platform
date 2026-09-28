// AI-assisted
package com.a07.server.knowledge;

import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * T-022 / BUG-016：v_table_meta 种子验证。
 * H2 MODE=MySQL + Flyway V1–V5；JdbcTemplate 直查 v_table_meta（无 REST API，平台库内部表）。
 * V5 幂等并入 production_orders + inventory_records 两表元数据。
 */
@SpringBootTest
class V5TableMetaSeedTests {

    @Autowired
    private JdbcTemplate jdbc;

    @Test
    @DisplayName("V5 种子：v_table_meta 含 production_orders 与 inventory_records")
    void v5_seeds_two_table_meta_rows() {
        List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT table_name, description, columns_json FROM v_table_meta WHERE table_name IN (?, ?)",
                "production_orders", "inventory_records");
        assertEquals(2, rows.size(), "v_table_meta 应含 production_orders + inventory_records 两行，实际: " + rows);

        for (Map<String, Object> row : rows) {
            String tableName = (String) row.get("table_name");
            String description = (String) row.get("description");
            String columnsJson = (String) row.get("columns_json");
            assertNotNull(description, tableName + " description 不应为 null");
            assertNotNull(columnsJson, tableName + " columns_json 不应为 null");
            assertTrue(columnsJson.startsWith("["), tableName + " columns_json 应为 JSON 数组: " + columnsJson);
        }
    }

    @Test
    @DisplayName("V5 种子：production_orders columns_json 含工单关键字段")
    void v5_production_orders_columns_json_fields() {
        String columnsJson = jdbc.queryForObject(
                "SELECT columns_json FROM v_table_meta WHERE table_name = 'production_orders'", String.class);
        assertNotNull(columnsJson);
        for (String field : new String[] {
                "order_no", "product_id", "production_line",
                "planned_qty", "completed_qty", "status",
                "planned_start", "planned_end", "actual_start", "actual_end"}) {
            assertTrue(columnsJson.contains("\"" + field + "\""),
                    "production_orders columns_json 应含字段 " + field + ": " + columnsJson);
        }
    }

    @Test
    @DisplayName("V5 种子：inventory_records columns_json 含库存关键字段")
    void v5_inventory_records_columns_json_fields() {
        String columnsJson = jdbc.queryForObject(
                "SELECT columns_json FROM v_table_meta WHERE table_name = 'inventory_records'", String.class);
        assertNotNull(columnsJson);
        for (String field : new String[] {
                "record_date", "warehouse", "product_id",
                "inventory_qty", "inbound_qty", "outbound_qty"}) {
            assertTrue(columnsJson.contains("\"" + field + "\""),
                    "inventory_records columns_json 应含字段 " + field + ": " + columnsJson);
        }
    }

    @Test
    @DisplayName("V5 幂等：重复执行不产生重复行")
    void v5_idempotent_no_duplicates() {
        Integer count = jdbc.queryForObject(
                "SELECT COUNT(*) FROM v_table_meta WHERE table_name IN ('production_orders', 'inventory_records')",
                Integer.class);
        assertEquals(2, count, "两表元数据不应重复，实际 count=" + count);
    }
}
