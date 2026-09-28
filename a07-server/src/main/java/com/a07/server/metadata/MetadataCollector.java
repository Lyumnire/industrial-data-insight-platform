// AI-assisted
package com.a07.server.metadata;

import java.nio.ByteBuffer;
import java.nio.CharBuffer;
import java.nio.charset.Charset;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.Set;
import java.util.regex.Pattern;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * JDBC 元数据采集器（S3，评分点2）：
 * 通过 DatabaseMetaData 读取表/列/注释/主键/外键，样例值 ≤5 条。
 * 表名/列名白名单校验后再拼 SQL（防注入，红线 R9 精神）。
 */
@Component
public class MetadataCollector {

    private static final Logger log = LoggerFactory.getLogger(MetadataCollector.class);

    private static final Pattern SAFE_IDENTIFIER = Pattern.compile("^[A-Za-z0-9_]+$");
    private static final int SAMPLE_LIMIT = 5;
    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** 采集结果：一次性返回所有元数据实体，由 Service 层负责落库。 */
    public record CollectionResult(List<TableMetadataEntity> tables,
                                   List<ColumnMetadataEntity> columns,
                                   List<TableRelationshipEntity> relationships) {
    }

    /**
     * 连接数据源并采集全部元数据。
     *
     * @throws SQLException 连接失败或元数据读取失败
     */
    public CollectionResult collect(DataSourceEntity dataSource, String plainPassword)
            throws SQLException {
        List<TableMetadataEntity> tables = new ArrayList<>();
        List<ColumnMetadataEntity> columns = new ArrayList<>();
        List<TableRelationshipEntity> relationships = new ArrayList<>();

        try (Connection conn = openConnection(dataSource, plainPassword)) {
            DatabaseMetaData meta = conn.getMetaData();
            String schema = resolveSchema(dataSource, conn);

            List<String> tableNames = collectTableNames(meta, schema);
            log.info("metadata_collect_begin dataSourceId={} tables={}", dataSource.getId(), tableNames.size());

            for (String tableName : tableNames) {
                if (!isSafeIdentifier(tableName)) {
                    log.warn("metadata_skip_unsafe_table name={}", tableName);
                    continue;
                }

                TableMetadataEntity tableEntity = new TableMetadataEntity();
                tableEntity.setDataSourceId(dataSource.getId());
                tableEntity.setTableName(tableName);
                tableEntity.setTableType("BASE TABLE");
                tableEntity.setCollectedAt(LocalDateTime.now());

                String comment = readTableComment(meta, schema, tableName);
                tableEntity.setTableComment(comment);
                tableEntity.setRowCount(readRowCount(conn, tableName));
                tables.add(tableEntity);

                Set<String> pkColumns = readPrimaryKeys(meta, schema, tableName);
                collectColumns(conn, meta, schema, tableName, dataSource.getId(), pkColumns, columns);
                collectRelationships(meta, schema, tableName, dataSource.getId(), relationships);
            }
        }

        log.info("metadata_collect_end dataSourceId={} tables={} columns={} relations={}",
                dataSource.getId(), tables.size(), columns.size(), relationships.size());
        return new CollectionResult(tables, columns, relationships);
    }

    /** 仅测试连通性并返回表数量，不落库。 */
    public MetadataDtos.ConnectionTestResult testConnection(DataSourceEntity dataSource, String plainPassword) {
        try (Connection conn = openConnection(dataSource, plainPassword)) {
            DatabaseMetaData meta = conn.getMetaData();
            String schema = resolveSchema(dataSource, conn);
            List<String> tableNames = collectTableNames(meta, schema);
            return new MetadataDtos.ConnectionTestResult(true, "连接成功", tableNames.size());
        } catch (SQLException e) {
            log.warn("metadata_test_connection_failed dataSourceId={} reason={}",
                    dataSource.getId(), e.getMessage());
            return new MetadataDtos.ConnectionTestResult(false, "连接失败: " + e.getMessage(), null);
        }
    }

    // ==================== 私有方法 ====================

    private Connection openConnection(DataSourceEntity ds, String plainPassword) throws SQLException {
        // 设置超时，红线 R8
        DriverManager.setLoginTimeout(10);
        // T-033/BUG-026：MySQL URL 自动补 characterEncoding=UTF-8（已有则不覆盖）
        String url = ensureMySqlUtf8(ds.getJdbcUrl());
        if (url.regionMatches(true, 0, "jdbc:mysql:", 0, "jdbc:mysql:".length()) && !hasCharacterEncodingParam(url)) {
            // 理论上 ensureMySqlUtf8 已补全；此处仅当未来改写策略时兜底 Connection Properties
            Properties props = new Properties();
            if (ds.getUsername() != null) props.setProperty("user", ds.getUsername());
            if (plainPassword != null) props.setProperty("password", plainPassword);
            props.setProperty("characterEncoding", "UTF-8");
            props.setProperty("useUnicode", "true");
            return DriverManager.getConnection(url, props);
        }
        return DriverManager.getConnection(url, ds.getUsername(), plainPassword);
    }

    /**
     * MySQL JDBC URL 自动补 {@code characterEncoding=UTF-8}（T-033/BUG-026）。
     * 已有 {@code characterEncoding}（任意取值）则不覆盖；非 {@code jdbc:mysql:} 前缀原样返回。
     * <p>注意：工单写 utf8mb4，但 Connector/J 的 characterEncoding 是 <b>Java charset 名</b>；
     * 实测 8.3.0 对 {@code utf8mb4} 抛 {@code Unsupported character encoding}，合法值为 {@code UTF-8}/{@code utf8}。
     */
    static String ensureMySqlUtf8(String jdbcUrl) {
        if (jdbcUrl == null || jdbcUrl.isBlank()) {
            return jdbcUrl;
        }
        if (!jdbcUrl.regionMatches(true, 0, "jdbc:mysql:", 0, "jdbc:mysql:".length())) {
            return jdbcUrl;
        }
        if (hasCharacterEncodingParam(jdbcUrl)) {
            return jdbcUrl;
        }
        int q = jdbcUrl.indexOf('?');
        if (q < 0) {
            return jdbcUrl + "?characterEncoding=UTF-8";
        }
        if (jdbcUrl.endsWith("?") || jdbcUrl.endsWith("&")) {
            return jdbcUrl + "characterEncoding=UTF-8";
        }
        return jdbcUrl + "&characterEncoding=UTF-8";
    }

    /** 查询串中是否已声明 characterEncoding（键大小写不敏感；已有则不覆盖）。 */
    private static boolean hasCharacterEncodingParam(String jdbcUrl) {
        int q = jdbcUrl.indexOf('?');
        if (q < 0) {
            return false;
        }
        for (String part : jdbcUrl.substring(q + 1).split("&")) {
            int eq = part.indexOf('=');
            String key = (eq >= 0 ? part.substring(0, eq) : part).trim();
            if ("characterEncoding".equalsIgnoreCase(key)) {
                return true;
            }
        }
        return false;
    }

    /**
     * 修复 REMARKS 采集乱码（T-033/BUG-026）：UTF-8 字节被按 windows-1252/latin1 误解码后再存 UTF-8
     * （如「设」→ è®¾）。仅在逆变换后 CJK 变多时回写，ASCII/正常西文原样保留。
     */
    static String repairMojibake(String s) {
        if (s == null || s.isBlank()) {
            return s;
        }
        boolean hasHigh = s.codePoints().anyMatch(c -> c >= 0x80);
        if (!hasHigh) {
            return s;
        }
                // 优先 ISO-8859-1；CP1252 未定义字节会让 REPORT 失败并放弃修复
        String best = tryReverseCharset(s, "ISO-8859-1");
        if (best == null) {
            best = tryReverseCharset(s, "windows-1252");
        }
        if (best == null) {
            return s;
        }
        long cjkOrig = s.codePoints().filter(MetadataCollector::isCjk).count();
        long cjkFixed = best.codePoints().filter(MetadataCollector::isCjk).count();
        return cjkFixed > cjkOrig ? best : s;
    }

    /**
     * mojibake 串还原为原始字节再按 UTF-8 解码。
     * 同时覆盖 latin1（U+0080-U+00FF）与 CP1252 特殊码点（如 U+2021、U+0153），
     * 避免单字符集 REPORT/REPLACE 漏映射（BUG-026 残留根因）。
     */
    private static String tryReverseCharset(String s, String charsetName) {
        try {
            java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream(s.length());
            for (int i = 0; i < s.length(); ) {
                int cp = s.codePointAt(i);
                i += Character.charCount(cp);
                int b = mojibakeByte(cp);
                if (b < 0) {
                    return null;
                }
                out.write(b);
            }
            byte[] raw = out.toByteArray();
            if (raw.length < 2) {
                return null;
            }
            String decoded = new String(raw, StandardCharsets.UTF_8);
            if (decoded.indexOf('\uFFFD') >= 0) {
                return null;
            }
            return decoded;
        } catch (Exception e) {
            return null;
        }
    }

    /** CP1252/latin1 误解码产生的码点 → 原始字节；无法映射返回 -1。 */
    private static int mojibakeByte(int cp) {
        if (cp >= 0x00 && cp <= 0xFF) {
            return cp;
        }
        switch (cp) {
            case 0x20AC: return 0x80;
            case 0x201A: return 0x82;
            case 0x0192: return 0x83;
            case 0x201E: return 0x84;
            case 0x2026: return 0x85;
            case 0x2020: return 0x86;
            case 0x2021: return 0x87;
            case 0x02C6: return 0x88;
            case 0x2030: return 0x89;
            case 0x0160: return 0x8A;
            case 0x2039: return 0x8B;
            case 0x0152: return 0x8C;
            case 0x017D: return 0x8E;
            case 0x2018: return 0x91;
            case 0x2019: return 0x92;
            case 0x201C: return 0x93;
            case 0x201D: return 0x94;
            case 0x2022: return 0x95;
            case 0x2013: return 0x96;
            case 0x2014: return 0x97;
            case 0x02DC: return 0x98;
            case 0x2122: return 0x99;
            case 0x0161: return 0x9A;
            case 0x203A: return 0x9B;
            case 0x0153: return 0x9C;
            case 0x017E: return 0x9E;
            case 0x0178: return 0x9F;
            default: return -1;
        }
    }
    private static boolean isCjk(int cp) {
        return (cp >= 0x4E00 && cp <= 0x9FFF)
                || (cp >= 0x3400 && cp <= 0x4DBF)
                || (cp >= 0xF900 && cp <= 0xFAFF);
    }

    /** H2 / MySQL 的 schema 解析：H2 DATABASE_TO_LOWER=TRUE 时 schema 为小写 public；MySQL 从 catalog 取。 */
    private static String resolveSchema(DataSourceEntity ds, Connection conn) throws SQLException {
        if ("h2".equalsIgnoreCase(ds.getDbType())) {
            // DATABASE_TO_LOWER=TRUE 时 H2 内部 schema 名为小写
            return "public";
        }
        String catalog = conn.getCatalog();
        return catalog != null ? catalog : null;
    }

    private List<String> collectTableNames(DatabaseMetaData meta, String schema) throws SQLException {
        List<String> names = new ArrayList<>();
        // 同时尝试传入 schema 和 null（覆盖大小写差异与无 schema 场景）
        for (String trySchema : new String[]{schema, schema == null ? null : schema.toLowerCase()}) {
            try (ResultSet rs = meta.getTables(null, trySchema, "%", new String[]{"TABLE", "BASE TABLE"})) {
                while (rs.next()) {
                    String name = rs.getString("TABLE_NAME");
                    if (name != null && !name.startsWith("INFORMATION_SCHEMA")
                            && !name.startsWith("information_schema")
                            && !name.startsWith("SYS_")
                            && !names.contains(name)) {
                        names.add(name);
                    }
                }
            }
        }
        // 若指定 schema 查不到，再用 null schema 兜底
        if (names.isEmpty()) {
            try (ResultSet rs = meta.getTables(null, null, "%", new String[]{"TABLE", "BASE TABLE"})) {
                while (rs.next()) {
                    String name = rs.getString("TABLE_NAME");
                    String tblSchema = rs.getString("TABLE_SCHEM");
                    if (name != null && !name.startsWith("INFORMATION_SCHEMA")
                            && !name.startsWith("information_schema")
                            && !name.startsWith("SYS_")
                            && !name.startsWith("flyway")
                            && (tblSchema == null || tblSchema.equalsIgnoreCase("public"))
                            && !names.contains(name)) {
                        names.add(name);
                    }
                }
            }
        }
        return names;
    }

    private static String readTableComment(DatabaseMetaData meta, String schema, String tableName) {
        try (ResultSet rs = meta.getTables(null, schema, tableName, null)) {
            if (rs.next()) {
                // T-033/BUG-026：源库 COMMENT 可能已是双重编码，采集时修复
                return repairMojibake(rs.getString("REMARKS"));
            }
        } catch (SQLException e) {
            log.debug("read_table_comment_failed table={} reason={}", tableName, e.getMessage());
        }
        return null;
    }

    private static long readRowCount(Connection conn, String tableName) {
        if (!isSafeIdentifier(tableName)) {
            return 0;
        }
        String sql = "SELECT COUNT(*) FROM \"" + tableName + "\"";
        // MySQL 用反引号更安全，但 H2 MODE=MySQL 也支持双引号；统一用反引号
        sql = "SELECT COUNT(*) FROM `" + tableName + "`";
        try (PreparedStatement ps = conn.prepareStatement(sql);
             ResultSet rs = ps.executeQuery()) {
            return rs.next() ? rs.getLong(1) : 0;
        } catch (SQLException e) {
            log.debug("read_row_count_failed table={} reason={}", tableName, e.getMessage());
            return 0;
        }
    }

    private static Set<String> readPrimaryKeys(DatabaseMetaData meta, String schema, String tableName) {
        Set<String> pks = new HashSet<>();
        try (ResultSet rs = meta.getPrimaryKeys(null, schema, tableName)) {
            while (rs.next()) {
                String col = rs.getString("COLUMN_NAME");
                if (col != null) {
                    pks.add(col);
                }
            }
        } catch (SQLException e) {
            log.debug("read_primary_keys_failed table={} reason={}", tableName, e.getMessage());
        }
        return pks;
    }

    private void collectColumns(Connection conn, DatabaseMetaData meta, String schema,
                                String tableName, Long dataSourceId,
                                Set<String> pkColumns, List<ColumnMetadataEntity> output)
            throws SQLException {
        try (ResultSet rs = meta.getColumns(null, schema, tableName, "%")) {
            while (rs.next()) {
                String colName = rs.getString("COLUMN_NAME");
                if (colName == null || !isSafeIdentifier(colName)) {
                    continue;
                }
                ColumnMetadataEntity col = new ColumnMetadataEntity();
                col.setDataSourceId(dataSourceId);
                col.setTableName(tableName);
                col.setColumnName(colName);
                col.setOrdinal(rs.getInt("ORDINAL_POSITION"));
                col.setDataType(rs.getString("TYPE_NAME")
                        + formatSize(rs.getInt("COLUMN_SIZE"), rs.getString("TYPE_NAME")));
                col.setNullable("NO".equalsIgnoreCase(rs.getString("IS_NULLABLE")) ? "NO" : "YES");
                col.setPrimaryKey(pkColumns.contains(colName) ? "YES" : "NO");
                col.setColumnComment(repairMojibake(rs.getString("REMARKS")));
                col.setSampleValues(collectSampleValues(conn, tableName, colName));
                output.add(col);
            }
        }
    }

    private static String formatSize(int size, String typeName) {
        if (typeName == null) return "";
        String upper = typeName.toUpperCase();
        if (upper.contains("CHAR") || upper.contains("BINARY") || upper.contains("DECIMAL")
                || upper.contains("NUMERIC")) {
            return "(" + size + ")";
        }
        return "";
    }

    private static String collectSampleValues(Connection conn, String tableName, String columnName) {
        if (!isSafeIdentifier(tableName) || !isSafeIdentifier(columnName)) {
            return "[]";
        }
        String sql = "SELECT DISTINCT `" + columnName + "` FROM `" + tableName
                + "` WHERE `" + columnName + "` IS NOT NULL LIMIT " + SAMPLE_LIMIT;
        List<String> samples = new ArrayList<>();
        try (PreparedStatement ps = conn.prepareStatement(sql);
             ResultSet rs = ps.executeQuery()) {
            while (rs.next() && samples.size() < SAMPLE_LIMIT) {
                Object val = rs.getObject(1);
                if (val != null) {
                    String s = String.valueOf(val);
                    if (s.length() > 100) s = s.substring(0, 100);
                    samples.add(s);
                }
            }
        } catch (SQLException e) {
            log.debug("collect_sample_values_failed table={} col={} reason={}",
                    tableName, columnName, e.getMessage());
        }
        try {
            return MAPPER.writeValueAsString(samples);
        } catch (Exception e) {
            return "[]";
        }
    }

    private static void collectRelationships(DatabaseMetaData meta, String schema,
                                             String tableName, Long dataSourceId,
                                             List<TableRelationshipEntity> output) {
        try (ResultSet rs = meta.getImportedKeys(null, schema, tableName)) {
            while (rs.next()) {
                TableRelationshipEntity rel = new TableRelationshipEntity();
                rel.setDataSourceId(dataSourceId);
                rel.setSourceTable(tableName);
                rel.setSourceColumn(rs.getString("FKCOLUMN_NAME"));
                rel.setTargetTable(rs.getString("PKTABLE_NAME"));
                rel.setTargetColumn(rs.getString("PKCOLUMN_NAME"));
                rel.setRelationType("fk");
                rel.setCreatedAt(LocalDateTime.now());
                output.add(rel);
            }
        } catch (SQLException e) {
            log.debug("collect_relationships_failed table={} reason={}", tableName, e.getMessage());
        }
    }

    /** 表名/列名白名单：仅允许字母数字下划线（防 SQL 注入）。 */
    static boolean isSafeIdentifier(String name) {
        return name != null && SAFE_IDENTIFIER.matcher(name).matches();
    }
}
