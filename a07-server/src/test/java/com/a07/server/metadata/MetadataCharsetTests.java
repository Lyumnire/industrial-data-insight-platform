// AI-assisted
package com.a07.server.metadata;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * T-033 / BUG-026：MySQL JDBC URL 自动补 characterEncoding + REMARKS 双重编码修复。
 * 纯单元测试（不启 Spring）。
 */
class MetadataCharsetTests {

    // ==================== ensureMySqlUtf8 ====================

    @Test
    @DisplayName("MySQL URL 无查询串：追加 ?characterEncoding=UTF-8")
    void mysql_url_without_query_appends_encoding() {
        assertEquals(
                "jdbc:mysql://localhost:3306/mes_demo?characterEncoding=UTF-8",
                MetadataCollector.ensureMySqlUtf8("jdbc:mysql://localhost:3306/mes_demo"));
    }

    @Test
    @DisplayName("MySQL URL 已有查询串：追加 &characterEncoding=UTF-8")
    void mysql_url_with_query_appends_encoding() {
        assertEquals(
                "jdbc:mysql://localhost:3306/mes_demo?useSSL=false&characterEncoding=UTF-8",
                MetadataCollector.ensureMySqlUtf8("jdbc:mysql://localhost:3306/mes_demo?useSSL=false"));
    }

    @Test
    @DisplayName("已有 characterEncoding（含 utf8）不覆盖")
    void existing_character_encoding_not_overwritten() {
        String withUtf8 = "jdbc:mysql://h:3306/db?characterEncoding=utf8&useSSL=false";
        assertEquals(withUtf8, MetadataCollector.ensureMySqlUtf8(withUtf8));

        String withGb = "jdbc:mysql://h:3306/db?useSSL=false&characterEncoding=gbk";
        assertEquals(withGb, MetadataCollector.ensureMySqlUtf8(withGb));

        String caseInsensitive = "jdbc:mysql://h:3306/db?CharacterEncoding=UTF-8";
        assertEquals(caseInsensitive, MetadataCollector.ensureMySqlUtf8(caseInsensitive));
    }

    @Test
    @DisplayName("非 MySQL URL（H2/null/空）原样返回")
    void non_mysql_urls_untouched() {
        String h2 = "jdbc:h2:mem:meta_test_source;MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1";
        assertEquals(h2, MetadataCollector.ensureMySqlUtf8(h2));
        assertNull(MetadataCollector.ensureMySqlUtf8(null));
        assertEquals("", MetadataCollector.ensureMySqlUtf8(""));
    }

    @Test
    @DisplayName("URL 以 ? 或 & 结尾时不重复分隔符")
    void trailing_separator_not_duplicated() {
        assertEquals("jdbc:mysql://h:3306/db?characterEncoding=UTF-8",
                MetadataCollector.ensureMySqlUtf8("jdbc:mysql://h:3306/db?"));
        assertEquals("jdbc:mysql://h:3306/db?useSSL=false&characterEncoding=UTF-8",
                MetadataCollector.ensureMySqlUtf8("jdbc:mysql://h:3306/db?useSSL=false&"));
    }

    @Test
    @DisplayName("jdbc:mysql:loadbalance: 等变体同样补全")
    void mysql_subprotocol_variants() {
        String lb = "jdbc:mysql:loadbalance://h1,h2/db";
        assertTrue(MetadataCollector.ensureMySqlUtf8(lb).contains("characterEncoding=UTF-8"));
    }

    // ==================== repairMojibake ====================

    @Test
    @DisplayName("双重编码中文（UTF-8 被按 CP1252 误解码）可逆修复")
    void repairs_double_encoded_chinese() {
        // 「设备」UTF-8 = E8 AE BE E5 A4 87 → 按 CP1252 读成 è®¾å¤‡ → 再存 UTF-8
        String mojibake = "è®¾å¤‡"; // è®¾å¤‡
        assertEquals("设备", MetadataCollector.repairMojibake(mojibake));
    }

    @Test
    @DisplayName("正常中文 / ASCII / 空 保持原样")
    void keeps_normal_text() {
        assertEquals("设备停机表", MetadataCollector.repairMojibake("设备停机表"));
        assertEquals("WidgetA", MetadataCollector.repairMojibake("WidgetA"));
        assertEquals("", MetadataCollector.repairMojibake(""));
        assertNull(MetadataCollector.repairMojibake(null));
    }

    @Test
    @DisplayName("无法逆变换的西文（无 CJK 增益）保持原样")
    void keeps_plain_latin_when_no_gain() {
        String latin = "café";
        assertEquals(latin, MetadataCollector.repairMojibake(latin));
        assertFalse(MetadataCollector.repairMojibake(latin).isEmpty());
    }
}
