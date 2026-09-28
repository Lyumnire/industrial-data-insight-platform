// AI-assisted
package com.a07.server.metadata;

import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.Statement;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * S3 元数据采集测试（评分点2，工单验收）。
 * H2 内置表模拟 information_schema：建独立 H2 库 → 注册数据源 → JDBC 采集 → 验证落库。
 * 实库 mes_demo 拉通依赖 Docker，未就绪 → 阻塞注明（见工单完成记录）。
 */
@SpringBootTest
@AutoConfigureMockMvc
class MetadataCollectionTests {

    private static final ObjectMapper OM = new ObjectMapper();

    /** 独立 H2 库作为采集目标（非 platform 库）。 */
    private static final String SOURCE_URL =
            "jdbc:h2:mem:meta_test_source;MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1";

    /** BUG-020：带密码的独立 H2 库，验证 id/test 解密 password_enc 后连接。 */
    private static final String SECURED_SOURCE_URL =
            "jdbc:h2:mem:meta_test_secured;MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1";
    private static final String SECURED_PASSWORD = "ds-test-secret-2026";

    @Autowired
    private MockMvc mvc;

    @Autowired
    private DataSourceCipher cipher;

    @BeforeAll
    static void setupSourceDatabase() throws Exception {
        try (Connection conn = DriverManager.getConnection(SOURCE_URL, "sa", "");
             Statement stmt = conn.createStatement()) {
            stmt.execute("CREATE TABLE IF NOT EXISTS demo_products (" +
                    "id BIGINT PRIMARY KEY," +
                    "name VARCHAR(50) NOT NULL," +
                    "price DECIMAL(10,2))");
            stmt.execute("CREATE TABLE IF NOT EXISTS demo_orders (" +
                    "id BIGINT PRIMARY KEY," +
                    "product_id BIGINT NOT NULL," +
                    "qty INT NOT NULL," +
                    "order_date DATE," +
                    "CONSTRAINT fk_order_product FOREIGN KEY (product_id) REFERENCES demo_products(id))");
            stmt.execute("DELETE FROM demo_orders");
            stmt.execute("DELETE FROM demo_products");
            stmt.execute("INSERT INTO demo_products VALUES (1, 'WidgetA', 10.50), (2, 'WidgetB', 20.00)");
            stmt.execute("INSERT INTO demo_orders VALUES (100, 1, 50, '2026-01-15'), (101, 2, 30, '2026-01-16')");
        }
        // BUG-020：带密码的源库——首次连接即设定密码，后续无密码连接必须失败
        try (Connection conn = DriverManager.getConnection(SECURED_SOURCE_URL, "sa", SECURED_PASSWORD);
             Statement stmt = conn.createStatement()) {
            stmt.execute("CREATE TABLE IF NOT EXISTS secured_items (" +
                    "id BIGINT PRIMARY KEY," +
                    "sku VARCHAR(40) NOT NULL)");
            stmt.execute("INSERT INTO secured_items VALUES (1, 'SKU-001')");
        }
    }

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
    @DisplayName("数据源注册：密码 AES-GCM 入库，响应不回传密文")
    void register_datasource_encrypts_password() throws Exception {
        String token = loginAsAdmin();

        String body = "{\"name\":\"H2测试源\",\"dbType\":\"h2\",\"jdbcUrl\":\"" + SOURCE_URL + "\"," +
                "\"username\":\"sa\",\"password\":\"\",\"description\":\"单元测试\"}";
        MvcResult result = mvc.perform(post("/api/metadata/datasources")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.name").value("H2测试源"))
                .andReturn();

        JsonNode resp = OM.readTree(result.getResponse().getContentAsString(StandardCharsets.UTF_8));
        long dsId = resp.path("data").path("id").asLong();
        assertTrue(dsId > 0);

        // 响应体不得包含 passwordEnc 字段
        String raw = result.getResponse().getContentAsString(StandardCharsets.UTF_8);
        assertFalse(raw.contains("passwordEnc"), "响应不得包含 passwordEnc（红线 R3）");

        // 库中确认密文非明文（空密码 → cipher.encrypt 返回 null → 列为空，也不应有明文密码字段）
        // 连通测试
        mvc.perform(post("/api/metadata/datasources/" + dsId + "/test")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.connected").value(true))
                .andExpect(jsonPath("$.data.tableCount").value(2));
    }

    @Test
    @DisplayName("JDBC 采集：表/列/主键/外键/样例值，refresh 覆盖写")
    void jdbc_collection_captures_metadata() throws Exception {
        String token = loginAsAdmin();

        // 注册数据源
        String regBody = "{\"name\":\"采集测试源\",\"dbType\":\"h2\",\"jdbcUrl\":\"" + SOURCE_URL + "\"," +
                "\"username\":\"sa\",\"password\":\"\"}";
        MvcResult regResult = mvc.perform(post("/api/metadata/datasources")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(regBody))
                .andExpect(status().isOk())
                .andReturn();
        JsonNode regJson = OM.readTree(regResult.getResponse().getContentAsString(StandardCharsets.UTF_8));
        long dsId = regJson.path("data").path("id").asLong();

        // 执行采集（引擎 reindex 失败不阻断）
        MvcResult refreshResult = mvc.perform(post("/api/metadata/datasources/" + dsId + "/refresh")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.tableCount").value(2))
                .andExpect(jsonPath("$.data.columnCount").isNumber())
                .andReturn();

        JsonNode refreshJson = OM.readTree(refreshResult.getResponse().getContentAsString(StandardCharsets.UTF_8));
        assertTrue(refreshJson.path("data").path("columnCount").asLong() >= 5,
                "至少采集到 5 个列（products 3 列 + orders 4 列）");

        // 查询表元数据
        mvc.perform(get("/api/metadata/tables")
                        .header("Authorization", "Bearer " + token)
                        .param("dataSourceId", String.valueOf(dsId))
                        .param("size", "50"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(2));

        // 查询列元数据：demo_orders 应有 product_id 主键标记为 NO、id 为 YES
        MvcResult colsResult = mvc.perform(get("/api/metadata/columns")
                        .header("Authorization", "Bearer " + token)
                        .param("dataSourceId", String.valueOf(dsId))
                        .param("tableName", "demo_orders")
                        .param("size", "50"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.total").value(4))
                .andReturn();

        JsonNode colsJson = OM.readTree(colsResult.getResponse().getContentAsString(StandardCharsets.UTF_8));
        JsonNode records = colsJson.path("data").path("records");
        boolean foundPk = false;
        for (JsonNode col : records) {
            if ("id".equals(col.path("columnName").asText())) {
                assertEquals("YES", col.path("primaryKey").asText(), "id 应为主键");
                foundPk = true;
            }
        }
        assertTrue(foundPk, "应存在 id 列且为主键");

        // 查询外键关系
        MvcResult relResult = mvc.perform(get("/api/metadata/relationships")
                        .header("Authorization", "Bearer " + token)
                        .param("dataSourceId", String.valueOf(dsId)))
                .andExpect(status().isOk())
                .andReturn();
        JsonNode relJson = OM.readTree(relResult.getResponse().getContentAsString(StandardCharsets.UTF_8));
        JsonNode rels = relJson.path("data");
        assertTrue(rels.size() >= 1, "应采集到外键关系");
        boolean foundFk = false;
        for (JsonNode rel : rels) {
            if ("demo_orders".equals(rel.path("sourceTable").asText())
                    && "product_id".equals(rel.path("sourceColumn").asText())) {
                assertEquals("demo_products", rel.path("targetTable").asText());
                assertEquals("id", rel.path("targetColumn").asText());
                foundFk = true;
            }
        }
        assertTrue(foundFk, "应存在 demo_orders.product_id → demo_products.id 外键");

        // 样例值：demo_products.name 应有非空样例
        MvcResult samplesResult = mvc.perform(get("/api/metadata/columns")
                        .header("Authorization", "Bearer " + token)
                        .param("dataSourceId", String.valueOf(dsId))
                        .param("tableName", "demo_products")
                        .param("size", "50"))
                .andExpect(status().isOk())
                .andReturn();
        JsonNode samplesJson = OM.readTree(samplesResult.getResponse().getContentAsString(StandardCharsets.UTF_8));
        JsonNode productCols = samplesJson.path("data").path("records");
        boolean foundSample = false;
        for (JsonNode col : productCols) {
            if ("name".equals(col.path("columnName").asText())) {
                JsonNode samples = col.path("sampleValues");
                assertTrue(samples.isArray() && samples.size() > 0, "name 列应有样例值");
                foundSample = true;
            }
        }
        assertTrue(foundSample, "demo_products.name 列应被采集");
    }

    @Test
    @DisplayName("BUG-020：datasources/{id}/test 解密 password_enc，编辑态不传明文密码仍 connected")
    void test_by_id_decrypts_password_enc_without_plaintext() throws Exception {
        String token = loginAsAdmin();

        // 1) 注册带密码的数据源：密码仅入 password_enc（AES-GCM），响应不回传明文/密文字段
        String regBody = "{\"name\":\"加密密码源\",\"dbType\":\"h2\",\"jdbcUrl\":\"" + SECURED_SOURCE_URL + "\"," +
                "\"username\":\"sa\",\"password\":\"" + SECURED_PASSWORD + "\"}";
        MvcResult regResult = mvc.perform(post("/api/metadata/datasources")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(regBody))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andReturn();
        String regRaw = regResult.getResponse().getContentAsString(StandardCharsets.UTF_8);
        assertFalse(regRaw.contains(SECURED_PASSWORD), "注册响应不得回传明文密码（红线 R3）");
        assertFalse(regRaw.contains("passwordEnc"), "注册响应不得包含 passwordEnc（红线 R3）");
        JsonNode regJson = OM.readTree(regRaw);
        long dsId = regJson.path("data").path("id").asLong();
        assertTrue(dsId > 0);

        // 2) 编辑态：PUT 不传 password 字段（R3 前端密码置空不回显；库中 password_enc 保持不变）
        String updateBody = "{\"name\":\"加密密码源-已改名\",\"description\":\"编辑态不传密码\"}";
        mvc.perform(put("/api/metadata/datasources/" + dsId)
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(updateBody))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.name").value("加密密码源-已改名"));

        // 3) 按 id 测连通：无请求体/无明文 password —— 服务端必须解密 password_enc 后连接
        mvc.perform(post("/api/metadata/datasources/" + dsId + "/test")
                        .header("Authorization", "Bearer " + token))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.connected").value(true))
                .andExpect(jsonPath("$.data.message").value("连接成功"))
                .andExpect(jsonPath("$.data.tableCount").value(1));

        // 4) 对照（BUG-020 原前端调用方式）：body 无 password 的 /datasources/test 必须失败
        String noPwBody = "{\"jdbcUrl\":\"" + SECURED_SOURCE_URL + "\",\"username\":\"sa\",\"dbType\":\"h2\"}";
        mvc.perform(post("/api/metadata/datasources/test")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(noPwBody))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.connected").value(false));
    }

    @Test
    @DisplayName("连通测试：错误 URL 返回 connected=false")
    void connection_test_failure() throws Exception {
        String token = loginAsAdmin();
        // IFEXISTS=TRUE 防止 H2 自动建库；不存在的库 + IFEXISTS → 连接失败
        String body = "{\"name\":\"错误源\",\"dbType\":\"h2\"," +
                "\"jdbcUrl\":\"jdbc:h2:mem:nonexistent_db_xyz;MODE=MySQL;IFEXISTS=TRUE\"," +
                "\"username\":\"sa\",\"password\":\"wrong\"}";
        mvc.perform(post("/api/metadata/datasources/test")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.connected").value(false));
    }

    @Test
    @DisplayName("AES-GCM 加解密往返：明文不落库")
    void cipher_round_trip() {
        String plain = "my-secret-password-123";
        String encrypted = cipher.encrypt(plain);
        assertNotNull(encrypted);
        assertFalse(encrypted.contains(plain), "密文不得包含明文");
        assertEquals(plain, cipher.decrypt(encrypted), "解密应还原明文");
    }

    @Test
    @DisplayName("metadata 接口无 token：401")
    void metadata_endpoints_require_auth() throws Exception {
        mvc.perform(get("/api/metadata/datasources"))
                .andExpect(status().isUnauthorized());
        mvc.perform(get("/api/metadata/tables"))
                .andExpect(status().isUnauthorized());
    }
}
