// AI-assisted
package com.a07.server.knowledge;

import java.time.LocalDateTime;
import java.util.List;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * S2 知识实体对外 DTO（实体注释约定：JSON 列在实体层为 String，Service 对外转 List）。
 * 请求体与响应体共用 record；创建时 id/createdAt/updatedAt 为空，响应时回填。
 */
public final class KnowledgeDtos {

    private KnowledgeDtos() {
    }

    // ---------- 业务对象 ----------

    public record ObjectRequest(String code, String name, String description,
                                String domain, String status) {
    }

    public record ObjectResponse(Long id, String code, String name, String description,
                                 String domain, String status,
                                 LocalDateTime createdAt, LocalDateTime updatedAt) {
    }

    // ---------- 业务指标 ----------

    public record MetricRequest(String code, String name, String description,
                                String formulaSql, String unit, String domain,
                                List<String> sourceTables, List<String> sourceColumns,
                                String status) {
    }

    public record MetricResponse(Long id, String code, String name, String description,
                                 String formulaSql, String unit, String domain,
                                 List<String> sourceTables, List<String> sourceColumns,
                                 String status,
                                 LocalDateTime createdAt, LocalDateTime updatedAt) {
    }

    // ---------- 业务规则 ----------

    public record RuleRequest(String code, String name, String ruleType, String content,
                              List<String> appliesTo, String status) {
    }

    public record RuleResponse(Long id, String code, String name, String ruleType,
                               String content, List<String> appliesTo, String status,
                               LocalDateTime createdAt, LocalDateTime updatedAt) {
    }

    // ---------- 分析主题 ----------

    public record TopicRequest(String code, String name, String description, String domain,
                               List<String> relatedObjectIds, List<String> relatedMetricIds,
                               String status) {
    }

    public record TopicResponse(Long id, String code, String name, String description,
                                String domain, List<String> relatedObjectIds,
                                List<String> relatedMetricIds, String status,
                                LocalDateTime createdAt, LocalDateTime updatedAt) {
    }

    // ---------- 知识图谱 ----------

    /** 图节点：id=业务编码，type ∈ object|metric|rule|topic。 */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record GraphNode(String id, String type, String name, String domain,
                            String description, String extra) {
    }

    /** 图边：source/target 为业务编码，relation ∈ topic_object|topic_metric|rule_metric。 */
    public record GraphEdge(String source, String target, String relation) {
    }

    /** 图谱响应：供前端 AntV G6 渲染。 */
    public record GraphResponse(List<GraphNode> nodes, List<GraphEdge> edges) {
    }
}
