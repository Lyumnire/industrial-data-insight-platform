// AI-assisted
package com.a07.server.knowledge;

import java.util.Collections;
import java.util.List;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * 实体层 JSON TEXT 列 ⇄ 对外 List 的双向转换工具（实体注释约定）。
 * 解析失败返回空列表并记日志，不抛异常阻断查询（红线 R8：不裸吞，但知识查询不应因脏数据 500）。
 */
public final class JsonTextUtil {

    private static final org.slf4j.Logger log = org.slf4j.LoggerFactory.getLogger(JsonTextUtil.class);

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private JsonTextUtil() {
    }

    /** JSON 数组字符串 → List&lt;String&gt;；null/空白/解析失败返回空列表。 */
    public static List<String> parseList(String jsonText) {
        if (jsonText == null || jsonText.isBlank()) {
            return Collections.emptyList();
        }
        try {
            return MAPPER.readValue(jsonText, new TypeReference<List<String>>() {
            });
        } catch (JsonProcessingException e) {
            log.warn("json_parse_failed text={} reason={}", jsonText, e.getMessage());
            return Collections.emptyList();
        }
    }

    /** List&lt;String&gt; → JSON 数组字符串；null → "[]"。 */
    public static String toJson(List<String> list) {
        if (list == null || list.isEmpty()) {
            return "[]";
        }
        try {
            return MAPPER.writeValueAsString(list);
        } catch (JsonProcessingException e) {
            // 仅含 String 的 List 序列化不会失败，防御性兜底
            throw new IllegalStateException("JSON 序列化失败", e);
        }
    }
}
