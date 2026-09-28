// AI-assisted
package com.a07.server.knowledge;

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
import com.a07.server.knowledge.KnowledgeDtos.GraphResponse;
import com.a07.server.knowledge.KnowledgeDtos.MetricRequest;
import com.a07.server.knowledge.KnowledgeDtos.MetricResponse;
import com.a07.server.knowledge.KnowledgeDtos.ObjectRequest;
import com.a07.server.knowledge.KnowledgeDtos.ObjectResponse;
import com.a07.server.knowledge.KnowledgeDtos.RuleRequest;
import com.a07.server.knowledge.KnowledgeDtos.RuleResponse;
import com.a07.server.knowledge.KnowledgeDtos.TopicRequest;
import com.a07.server.knowledge.KnowledgeDtos.TopicResponse;

import jakarta.validation.Valid;

/**
 * S2 业务知识 REST 接口（评分点1）：四实体 CRUD + 知识图谱。
 * 新路径 authenticated（SecurityConfig anyRequest），细粒度 RBAC 记遗留。
 */
@RestController
@RequestMapping("/api/knowledge")
public class KnowledgeController {

    private final KnowledgeService knowledgeService;

    public KnowledgeController(KnowledgeService knowledgeService) {
        this.knowledgeService = knowledgeService;
    }

    // ==================== 业务对象 ====================

    @GetMapping("/objects")
    public ApiResult<PageResult<ObjectResponse>> listObjects(
            @RequestParam(required = false) String domain,
            @RequestParam(required = false) String status,
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size) {
        return ApiResult.ok(knowledgeService.listObjects(domain, status, page, size));
    }

    @GetMapping("/objects/{id}")
    public ApiResult<ObjectResponse> getObject(@PathVariable Long id) {
        return ApiResult.ok(knowledgeService.getObject(id));
    }

    @PostMapping("/objects")
    public ApiResult<ObjectResponse> createObject(@Valid @RequestBody ObjectRequest request) {
        return ApiResult.ok(knowledgeService.createObject(request));
    }

    @PutMapping("/objects/{id}")
    public ApiResult<ObjectResponse> updateObject(@PathVariable Long id,
                                                  @RequestBody ObjectRequest request) {
        return ApiResult.ok(knowledgeService.updateObject(id, request));
    }

    @DeleteMapping("/objects/{id}")
    public ApiResult<Void> deleteObject(@PathVariable Long id) {
        knowledgeService.deleteObject(id);
        return ApiResult.ok(null);
    }

    // ==================== 业务指标 ====================

    @GetMapping("/metrics")
    public ApiResult<PageResult<MetricResponse>> listMetrics(
            @RequestParam(required = false) String domain,
            @RequestParam(required = false) String status,
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size) {
        return ApiResult.ok(knowledgeService.listMetrics(domain, status, page, size));
    }

    @GetMapping("/metrics/{id}")
    public ApiResult<MetricResponse> getMetric(@PathVariable Long id) {
        return ApiResult.ok(knowledgeService.getMetric(id));
    }

    @PostMapping("/metrics")
    public ApiResult<MetricResponse> createMetric(@Valid @RequestBody MetricRequest request) {
        return ApiResult.ok(knowledgeService.createMetric(request));
    }

    @PutMapping("/metrics/{id}")
    public ApiResult<MetricResponse> updateMetric(@PathVariable Long id,
                                                  @RequestBody MetricRequest request) {
        return ApiResult.ok(knowledgeService.updateMetric(id, request));
    }

    @DeleteMapping("/metrics/{id}")
    public ApiResult<Void> deleteMetric(@PathVariable Long id) {
        knowledgeService.deleteMetric(id);
        return ApiResult.ok(null);
    }

    // ==================== 业务规则 ====================

    @GetMapping("/rules")
    public ApiResult<PageResult<RuleResponse>> listRules(
            @RequestParam(required = false) String domain,
            @RequestParam(required = false) String status,
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size) {
        return ApiResult.ok(knowledgeService.listRules(domain, status, page, size));
    }

    @GetMapping("/rules/{id}")
    public ApiResult<RuleResponse> getRule(@PathVariable Long id) {
        return ApiResult.ok(knowledgeService.getRule(id));
    }

    @PostMapping("/rules")
    public ApiResult<RuleResponse> createRule(@Valid @RequestBody RuleRequest request) {
        return ApiResult.ok(knowledgeService.createRule(request));
    }

    @PutMapping("/rules/{id}")
    public ApiResult<RuleResponse> updateRule(@PathVariable Long id,
                                              @RequestBody RuleRequest request) {
        return ApiResult.ok(knowledgeService.updateRule(id, request));
    }

    @DeleteMapping("/rules/{id}")
    public ApiResult<Void> deleteRule(@PathVariable Long id) {
        knowledgeService.deleteRule(id);
        return ApiResult.ok(null);
    }

    // ==================== 分析主题 ====================

    @GetMapping("/topics")
    public ApiResult<PageResult<TopicResponse>> listTopics(
            @RequestParam(required = false) String domain,
            @RequestParam(required = false) String status,
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "20") long size) {
        return ApiResult.ok(knowledgeService.listTopics(domain, status, page, size));
    }

    @GetMapping("/topics/{id}")
    public ApiResult<TopicResponse> getTopic(@PathVariable Long id) {
        return ApiResult.ok(knowledgeService.getTopic(id));
    }

    @PostMapping("/topics")
    public ApiResult<TopicResponse> createTopic(@Valid @RequestBody TopicRequest request) {
        return ApiResult.ok(knowledgeService.createTopic(request));
    }

    @PutMapping("/topics/{id}")
    public ApiResult<TopicResponse> updateTopic(@PathVariable Long id,
                                                @RequestBody TopicRequest request) {
        return ApiResult.ok(knowledgeService.updateTopic(id, request));
    }

    @DeleteMapping("/topics/{id}")
    public ApiResult<Void> deleteTopic(@PathVariable Long id) {
        knowledgeService.deleteTopic(id);
        return ApiResult.ok(null);
    }

    // ==================== 知识图谱 ====================

    @GetMapping("/graph")
    public ApiResult<GraphResponse> getGraph() {
        return ApiResult.ok(knowledgeService.buildGraph());
    }
}
