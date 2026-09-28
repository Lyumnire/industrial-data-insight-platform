// AI-assisted
package com.a07.server.knowledge;

import java.nio.charset.StandardCharsets;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.util.HashSet;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * S2 业务知识 CRUD + 图谱测试（评分点1，工单验收）。
 * H2 MODE=MySQL + Flyway V1-V4；MockMvc 走完整过滤器链（JWT）。
 * V4（T-018）覆盖：库存/工单 7 指标种子 + topic 关联 + 口径规则。
 */
@SpringBootTest
@AutoConfigureMockMvc
class KnowledgeCrudTests {

    private static final ObjectMapper OM = new ObjectMapper();

    @Autowired
    private MockMvc mvc;

    private String loginAsAdmin() throws Exception {
        MvcResult result = mvc.perform(post("/api/auth/login")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"admin\",\"password\":\"admin123\"}"))
                .andExpect(status().isOk())
                .andReturn();
        JsonNode body = OM.readTree(result.getResponse().getContentAsString(StandardCharsets.UTF_8));
        return body.path("data").path("token").asText();
    }

    // ==================== 业务对象 CRUD ====================

    @Test
    @DisplayName("对象 CRUD：创建→列表过滤→更新→删除")
    void object_crud_lifecycle() throws Exception {
        String token = loginAsAdmin();

        // 创建
        String createBody = "{\"code\":\"test_obj_crud\",\"name\":\"测试对象\",\"description\":\"CRUD 测试\"," +
                "\"domain\":\"生产\",\"status\":\"active\"}";
        MvcResult created = mvc.perform(post("/api/knowledge/objects")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(createBody))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.code").value("test_obj_crud"))
                .andReturn();
        JsonNode createdJson = OM.readTree(created.getResponse().getContentAsString(StandardCharsets.UTF_8));
        long id = createdJson.path("data").path("id").asLong();

        // 列表 + domain 过滤
        mvc.perform(get("/api/knowledge/objects")
                        .header("Authorization", "Bearer " + token)
                        .param("domain", "生产")
                        .param("page", "1")
                        .param("size", "50"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.total").isNumber());

        // 更新
        mvc.perform(put("/api/knowledge/objects/" + id)
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"测试对象改\",\"description\":\"已更新\",\"domain\":\"生产\",\"status\":\"active\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.name").value("测试对象改"));

        // 删除
        mvc.perform(delete("/api/knowledge/objects/" + id)
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0));

        // 删除后 GET 404
        mvc.perform(get("/api/knowledge/objects/" + id)
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isNotFound());
    }

    @Test
    @DisplayName("对象重复编码：409")
    void object_duplicate_code_conflict() throws Exception {
        String token = loginAsAdmin();
        String body = "{\"code\":\"product\",\"name\":\"重复产品\",\"description\":\"x\",\"domain\":\"生产\"}";
        mvc.perform(post("/api/knowledge/objects")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body))
                .andExpect(status().isConflict());
    }

    // ==================== 业务指标 CRUD ====================

    @Test
    @DisplayName("指标 CRUD：创建时 JSON 列转 List，响应为数组")
    void metric_crud_with_json_lists() throws Exception {
        String token = loginAsAdmin();

        String createBody = "{\"code\":\"test_metric_crud\",\"name\":\"测试指标\",\"description\":\"测试\"," +
                "\"formulaSql\":\"SUM(qty)\",\"unit\":\"件\",\"domain\":\"生产\"," +
                "\"sourceTables\":[\"process_output\"],\"sourceColumns\":[\"process_output.produced_qty\"]," +
                "\"status\":\"active\"}";
        MvcResult created = mvc.perform(post("/api/knowledge/metrics")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(createBody))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.sourceTables[0]").value("process_output"))
                .andExpect(jsonPath("$.data.sourceColumns[0]").value("process_output.produced_qty"))
                .andReturn();
        JsonNode createdJson = OM.readTree(created.getResponse().getContentAsString(StandardCharsets.UTF_8));
        long id = createdJson.path("data").path("id").asLong();

        // 更新 JSON 列
        mvc.perform(put("/api/knowledge/metrics/" + id)
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"sourceTables\":[\"process_output\",\"equipment_downtime\"]," +
                                "\"sourceColumns\":[\"process_output.produced_qty\"]}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.sourceTables.length()").value(2));

        mvc.perform(delete("/api/knowledge/metrics/" + id)
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk());
    }

    // ==================== 业务规则 CRUD ====================

    @Test
    @DisplayName("规则 CRUD：appliesTo JSON 数组正确往返")
    void rule_crud_with_applies_to() throws Exception {
        String token = loginAsAdmin();

        String createBody = "{\"code\":\"test_rule_crud\",\"name\":\"测试规则\",\"ruleType\":\"口径\"," +
                "\"content\":\"测试规则内容\",\"appliesTo\":[\"process_yield_rate\"],\"status\":\"active\"}";
        MvcResult created = mvc.perform(post("/api/knowledge/rules")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(createBody))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.appliesTo[0]").value("process_yield_rate"))
                .andReturn();
        JsonNode createdJson = OM.readTree(created.getResponse().getContentAsString(StandardCharsets.UTF_8));
        long id = createdJson.path("data").path("id").asLong();

        mvc.perform(delete("/api/knowledge/rules/" + id)
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk());
    }

    // ==================== 分析主题 CRUD ====================

    @Test
    @DisplayName("主题 CRUD：关联对象/指标编码 JSON 数组正确往返")
    void topic_crud_with_related_ids() throws Exception {
        String token = loginAsAdmin();

        String createBody = "{\"code\":\"test_topic_crud\",\"name\":\"测试主题\",\"description\":\"测试\"," +
                "\"domain\":\"生产\",\"relatedObjectIds\":[\"process\",\"product\"]," +
                "\"relatedMetricIds\":[\"output_qty\"],\"status\":\"active\"}";
        MvcResult created = mvc.perform(post("/api/knowledge/topics")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(createBody))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.relatedObjectIds.length()").value(2))
                .andExpect(jsonPath("$.data.relatedMetricIds[0]").value("output_qty"))
                .andReturn();
        JsonNode createdJson = OM.readTree(created.getResponse().getContentAsString(StandardCharsets.UTF_8));
        long id = createdJson.path("data").path("id").asLong();

        mvc.perform(delete("/api/knowledge/topics/" + id)
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk());
    }

    // ==================== 知识图谱 ====================

    @Test
    @DisplayName("知识图谱：种子数据组装节点+边，含对象/主题/指标/规则")
    void graph_assembles_nodes_and_edges() throws Exception {
        String token = loginAsAdmin();

        MvcResult result = mvc.perform(get("/api/knowledge/graph")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.nodes").isArray())
                .andExpect(jsonPath("$.data.edges").isArray())
                .andReturn();

        JsonNode body = OM.readTree(result.getResponse().getContentAsString(StandardCharsets.UTF_8));
        JsonNode data = body.path("data");
        JsonNode nodes = data.path("nodes");
        JsonNode edges = data.path("edges");

        assertTrue(nodes.size() > 0, "图谱应包含种子节点");

        // 验证四类节点均存在
        boolean hasObject = false, hasTopic = false, hasMetric = false, hasRule = false;
        for (JsonNode node : nodes) {
            String type = node.path("type").asText();
            switch (type) {
                case "object" -> hasObject = true;
                case "topic" -> hasTopic = true;
                case "metric" -> hasMetric = true;
                case "rule" -> hasRule = true;
                default -> { }
            }
        }
        assertTrue(hasObject, "应有 object 节点");
        assertTrue(hasTopic, "应有 topic 节点");
        assertTrue(hasMetric, "应有 metric 节点");
        assertTrue(hasRule, "应有 rule 节点");

        // 验证边的类型
        boolean hasTopicObjectEdge = false, hasTopicMetricEdge = false, hasRuleMetricEdge = false;
        for (JsonNode edge : edges) {
            String relation = edge.path("relation").asText();
            switch (relation) {
                case "topic_object" -> hasTopicObjectEdge = true;
                case "topic_metric" -> hasTopicMetricEdge = true;
                case "rule_metric" -> hasRuleMetricEdge = true;
                default -> { }
            }
        }
        assertTrue(hasTopicObjectEdge, "应有 topic_object 边");
        assertTrue(hasTopicMetricEdge, "应有 topic_metric 边");
        assertTrue(hasRuleMetricEdge, "应有 rule_metric 边");
    }

    @Test
    @DisplayName("知识图谱 V4：库存指标节点 + topic_inventory→库存指标 边")
    void graph_contains_inventory_metrics_after_v4() throws Exception {
        String token = loginAsAdmin();

        MvcResult result = mvc.perform(get("/api/knowledge/graph")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andReturn();

        JsonNode data = OM.readTree(result.getResponse().getContentAsString(StandardCharsets.UTF_8)).path("data");
        JsonNode nodes = data.path("nodes");
        JsonNode edges = data.path("edges");

        Set<String> metricNodeIds = new HashSet<>();
        for (JsonNode node : nodes) {
            if ("metric".equals(node.path("type").asText())) {
                metricNodeIds.add(node.path("id").asText());
            }
        }
        for (String code : new String[] {
                "inventory_qty", "inbound_qty", "outbound_qty",
                "inventory_turnover", "safety_stock_line",
                "order_count", "order_completion_rate"}) {
            assertTrue(metricNodeIds.contains(code), "图谱应含库存/工单指标节点: " + code);
        }

        boolean hasInventoryMetricEdge = false;
        boolean hasProductionOrderEdge = false;
        for (JsonNode edge : edges) {
            if (!"topic_metric".equals(edge.path("relation").asText())) {
                continue;
            }
            String source = edge.path("source").asText();
            String target = edge.path("target").asText();
            if ("topic_inventory".equals(source) && "inventory_qty".equals(target)) {
                hasInventoryMetricEdge = true;
            }
            if ("topic_production".equals(source) && "order_count".equals(target)) {
                hasProductionOrderEdge = true;
            }
        }
        assertTrue(hasInventoryMetricEdge, "应有 topic_inventory → inventory_qty 边");
        assertTrue(hasProductionOrderEdge, "应有 topic_production → order_count 边");
    }

    // ==================== 权限 ====================

    @Test
    @DisplayName("知识接口无 token：401")
    void knowledge_endpoints_require_auth() throws Exception {
        mvc.perform(get("/api/knowledge/objects"))
                .andExpect(status().isUnauthorized());
        mvc.perform(get("/api/knowledge/graph"))
                .andExpect(status().isUnauthorized());
        mvc.perform(post("/api/knowledge/objects")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isUnauthorized());
    }

    // ==================== 种子数据完整性 ====================

    @Test
    @DisplayName("种子数据 V2+V4：对象8/指标13/规则7/主题4 可查询")
    void seed_data_present() throws Exception {
        String token = loginAsAdmin();

        mvc.perform(get("/api/knowledge/objects")
                        .header("Authorization", "Bearer " + token)
                        .param("size", "100"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(8));

        // V2 原 6 条 + V4 库存/工单 7 条 = 13
        mvc.perform(get("/api/knowledge/metrics")
                        .header("Authorization", "Bearer " + token)
                        .param("size", "100"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(13));

        // V2 原 4 条 + V4 口径规则 3 条 = 7
        mvc.perform(get("/api/knowledge/rules")
                        .header("Authorization", "Bearer " + token)
                        .param("size", "100"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(7));

        mvc.perform(get("/api/knowledge/topics")
                        .header("Authorization", "Bearer " + token)
                        .param("size", "100"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(4));
    }

    @Test
    @DisplayName("V4 种子：7 条库存/工单指标可查，topic 关联已填")
    void v4_inventory_order_metrics_seeded() throws Exception {
        String token = loginAsAdmin();

        // ---- metrics 含 7 条新编码，且 formulaSql 与 T-015 口径一致 ----
        MvcResult metricsResult = mvc.perform(get("/api/knowledge/metrics")
                        .header("Authorization", "Bearer " + token)
                        .param("size", "100"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(13))
                .andReturn();
        JsonNode metrics = OM.readTree(metricsResult.getResponse().getContentAsString(StandardCharsets.UTF_8))
                .path("data").path("records");

        Set<String> found = new HashSet<>();
        for (JsonNode m : metrics) {
            String code = m.path("code").asText();
            if ("order_count".equals(code)) {
                assertEquals("COUNT(*)", m.path("formulaSql").asText());
                found.add(code);
            } else if ("order_completion_rate".equals(code)) {
                assertEquals("SUM(completed_qty)/NULLIF(SUM(planned_qty),0)", m.path("formulaSql").asText());
                found.add(code);
            } else if ("inventory_qty".equals(code)) {
                assertEquals("SUM(inventory_qty)", m.path("formulaSql").asText());
                found.add(code);
            } else if ("inbound_qty".equals(code)) {
                assertEquals("SUM(inbound_qty)", m.path("formulaSql").asText());
                found.add(code);
            } else if ("outbound_qty".equals(code)) {
                assertEquals("SUM(outbound_qty)", m.path("formulaSql").asText());
                found.add(code);
            } else if ("inventory_turnover".equals(code)) {
                assertEquals("SUM(outbound_qty)/NULLIF(AVG(inventory_qty),0)", m.path("formulaSql").asText());
                found.add(code);
            } else if ("safety_stock_line".equals(code)) {
                assertEquals("AVG(outbound_qty)*7", m.path("formulaSql").asText());
                found.add(code);
            }
        }
        assertEquals(7, found.size(), "V4 应并入 7 条库存/工单指标，实际找到: " + found);

        // ---- topics：inventory 5 指标 / production 追加 order 2 指标 ----
        MvcResult topicsResult = mvc.perform(get("/api/knowledge/topics")
                        .header("Authorization", "Bearer " + token)
                        .param("size", "100"))
                .andExpect(status().isOk())
                .andReturn();
        JsonNode topics = OM.readTree(topicsResult.getResponse().getContentAsString(StandardCharsets.UTF_8))
                .path("data").path("records");

        Set<String> inventoryMetrics = new HashSet<>();
        Set<String> productionMetrics = new HashSet<>();
        for (JsonNode t : topics) {
            String code = t.path("code").asText();
            if ("topic_inventory".equals(code)) {
                for (JsonNode id : t.path("relatedMetricIds")) {
                    inventoryMetrics.add(id.asText());
                }
            } else if ("topic_production".equals(code)) {
                for (JsonNode id : t.path("relatedMetricIds")) {
                    productionMetrics.add(id.asText());
                }
            }
        }
        assertTrue(inventoryMetrics.containsAll(Set.of(
                        "inventory_qty", "inbound_qty", "outbound_qty",
                        "inventory_turnover", "safety_stock_line")),
                "topic_inventory 应关联库存 5 指标，实际: " + inventoryMetrics);
        assertTrue(productionMetrics.contains("output_qty"),
                "topic_production 应保留 output_qty，实际: " + productionMetrics);
        assertTrue(productionMetrics.containsAll(Set.of("order_count", "order_completion_rate")),
                "topic_production 应追加工单 2 指标，实际: " + productionMetrics);

        // ---- rules：V4 口径规则可查 ----
        MvcResult rulesResult = mvc.perform(get("/api/knowledge/rules")
                        .header("Authorization", "Bearer " + token)
                        .param("size", "100"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(7))
                .andReturn();
        JsonNode rules = OM.readTree(rulesResult.getResponse().getContentAsString(StandardCharsets.UTF_8))
                .path("data").path("records");
        Set<String> ruleCodes = new HashSet<>();
        for (JsonNode r : rules) {
            ruleCodes.add(r.path("code").asText());
        }
        assertTrue(ruleCodes.containsAll(Set.of(
                        "rule_order_inventory_sum_before_divide",
                        "rule_safety_stock_daily_outbound_x7",
                        "rule_time_anchor_max_date")),
                "V4 应补 3 条口径规则，实际: " + ruleCodes);
    }
}
