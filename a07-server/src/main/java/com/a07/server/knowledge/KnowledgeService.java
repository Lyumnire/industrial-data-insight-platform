// AI-assisted
package com.a07.server.knowledge;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import com.a07.server.common.PageResult;
import com.a07.server.knowledge.KnowledgeDtos.GraphEdge;
import com.a07.server.knowledge.KnowledgeDtos.GraphNode;
import com.a07.server.knowledge.KnowledgeDtos.GraphResponse;
import com.a07.server.knowledge.KnowledgeDtos.ObjectRequest;
import com.a07.server.knowledge.KnowledgeDtos.ObjectResponse;
import com.a07.server.knowledge.KnowledgeDtos.MetricRequest;
import com.a07.server.knowledge.KnowledgeDtos.MetricResponse;
import com.a07.server.knowledge.KnowledgeDtos.RuleRequest;
import com.a07.server.knowledge.KnowledgeDtos.RuleResponse;
import com.a07.server.knowledge.KnowledgeDtos.TopicRequest;
import com.a07.server.knowledge.KnowledgeDtos.TopicResponse;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;

/**
 * S2 业务知识服务（评分点1）：四实体 CRUD + 图谱组装。
 * 列表支持 domain/status 过滤与分页；JSON 列在实体层为 String，本层对外转 List。
 */
@Service
public class KnowledgeService {

    private static final Logger log = LoggerFactory.getLogger(KnowledgeService.class);

    private final BusinessObjectMapper objectMapper;
    private final BusinessMetricMapper metricMapper;
    private final BusinessRuleMapper ruleMapper;
    private final AnalysisTopicMapper topicMapper;

    public KnowledgeService(BusinessObjectMapper objectMapper, BusinessMetricMapper metricMapper,
                            BusinessRuleMapper ruleMapper, AnalysisTopicMapper topicMapper) {
        this.objectMapper = objectMapper;
        this.metricMapper = metricMapper;
        this.ruleMapper = ruleMapper;
        this.topicMapper = topicMapper;
    }

    // ==================== 业务对象 ====================

    public PageResult<ObjectResponse> listObjects(String domain, String status, long page, long size) {
        Page<BusinessObjectEntity> p = new Page<>(page, size);
        Page<BusinessObjectEntity> result = objectMapper.selectPage(p,
                new LambdaQueryWrapper<BusinessObjectEntity>()
                        .eq(domain != null && !domain.isBlank(), BusinessObjectEntity::getDomain, domain)
                        .eq(status != null && !status.isBlank(), BusinessObjectEntity::getStatus, status)
                        .orderByAsc(BusinessObjectEntity::getId));
        return PageResult.of(result.getTotal(), page, size,
                result.getRecords().stream().map(this::toObjectResponse).toList());
    }

    public ObjectResponse getObject(Long id) {
        return toObjectResponse(requireObject(id));
    }

    @Transactional
    public ObjectResponse createObject(ObjectRequest req) {
        requireText(req.code(), "对象编码不能为空");
        requireText(req.name(), "对象名称不能为空");
        if (objectMapper.selectCount(new LambdaQueryWrapper<BusinessObjectEntity>()
                .eq(BusinessObjectEntity::getCode, req.code())) > 0) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "对象编码已存在: " + req.code());
        }
        BusinessObjectEntity e = new BusinessObjectEntity();
        e.setCode(req.code());
        e.setName(req.name());
        e.setDescription(req.description() == null ? "" : req.description());
        e.setDomain(req.domain() == null ? "" : req.domain());
        e.setStatus(defaultActive(req.status()));
        LocalDateTime now = LocalDateTime.now();
        e.setCreatedAt(now);
        e.setUpdatedAt(now);
        objectMapper.insert(e);
        log.info("knowledge_object_created code={}", e.getCode());
        return toObjectResponse(e);
    }

    @Transactional
    public ObjectResponse updateObject(Long id, ObjectRequest req) {
        BusinessObjectEntity e = requireObject(id);
        if (req.name() != null) e.setName(req.name());
        if (req.description() != null) e.setDescription(req.description());
        if (req.domain() != null) e.setDomain(req.domain());
        if (req.status() != null) e.setStatus(req.status());
        e.setUpdatedAt(LocalDateTime.now());
        objectMapper.updateById(e);
        return toObjectResponse(e);
    }

    @Transactional
    public void deleteObject(Long id) {
        requireObject(id);
        objectMapper.deleteById(id);
        log.info("knowledge_object_deleted id={}", id);
    }

    // ==================== 业务指标 ====================

    public PageResult<MetricResponse> listMetrics(String domain, String status, long page, long size) {
        Page<BusinessMetricEntity> p = new Page<>(page, size);
        Page<BusinessMetricEntity> result = metricMapper.selectPage(p,
                new LambdaQueryWrapper<BusinessMetricEntity>()
                        .eq(domain != null && !domain.isBlank(), BusinessMetricEntity::getDomain, domain)
                        .eq(status != null && !status.isBlank(), BusinessMetricEntity::getStatus, status)
                        .orderByAsc(BusinessMetricEntity::getId));
        return PageResult.of(result.getTotal(), page, size,
                result.getRecords().stream().map(this::toMetricResponse).toList());
    }

    public MetricResponse getMetric(Long id) {
        return toMetricResponse(requireMetric(id));
    }

    @Transactional
    public MetricResponse createMetric(MetricRequest req) {
        requireText(req.code(), "指标编码不能为空");
        requireText(req.name(), "指标名称不能为空");
        requireText(req.formulaSql(), "指标公式不能为空");
        if (metricMapper.selectCount(new LambdaQueryWrapper<BusinessMetricEntity>()
                .eq(BusinessMetricEntity::getCode, req.code())) > 0) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "指标编码已存在: " + req.code());
        }
        BusinessMetricEntity e = new BusinessMetricEntity();
        e.setCode(req.code());
        e.setName(req.name());
        e.setDescription(req.description() == null ? "" : req.description());
        e.setFormulaSql(req.formulaSql());
        e.setUnit(req.unit() == null ? "" : req.unit());
        e.setDomain(req.domain() == null ? "" : req.domain());
        e.setSourceTables(JsonTextUtil.toJson(req.sourceTables()));
        e.setSourceColumns(JsonTextUtil.toJson(req.sourceColumns()));
        e.setStatus(defaultActive(req.status()));
        LocalDateTime now = LocalDateTime.now();
        e.setCreatedAt(now);
        e.setUpdatedAt(now);
        metricMapper.insert(e);
        log.info("knowledge_metric_created code={}", e.getCode());
        return toMetricResponse(e);
    }

    @Transactional
    public MetricResponse updateMetric(Long id, MetricRequest req) {
        BusinessMetricEntity e = requireMetric(id);
        if (req.name() != null) e.setName(req.name());
        if (req.description() != null) e.setDescription(req.description());
        if (req.formulaSql() != null) e.setFormulaSql(req.formulaSql());
        if (req.unit() != null) e.setUnit(req.unit());
        if (req.domain() != null) e.setDomain(req.domain());
        if (req.sourceTables() != null) e.setSourceTables(JsonTextUtil.toJson(req.sourceTables()));
        if (req.sourceColumns() != null) e.setSourceColumns(JsonTextUtil.toJson(req.sourceColumns()));
        if (req.status() != null) e.setStatus(req.status());
        e.setUpdatedAt(LocalDateTime.now());
        metricMapper.updateById(e);
        return toMetricResponse(e);
    }

    @Transactional
    public void deleteMetric(Long id) {
        requireMetric(id);
        metricMapper.deleteById(id);
        log.info("knowledge_metric_deleted id={}", id);
    }

    // ==================== 业务规则 ====================

    public PageResult<RuleResponse> listRules(String domain, String status, long page, long size) {
        Page<BusinessRuleEntity> p = new Page<>(page, size);
        // business_rules 表无 domain 列，domain 过滤降级为 status 过滤 + 全量分页（图谱/前端按 ruleType 筛选）
        Page<BusinessRuleEntity> result = ruleMapper.selectPage(p,
                new LambdaQueryWrapper<BusinessRuleEntity>()
                        .eq(status != null && !status.isBlank(), BusinessRuleEntity::getStatus, status)
                        .orderByAsc(BusinessRuleEntity::getId));
        return PageResult.of(result.getTotal(), page, size,
                result.getRecords().stream().map(this::toRuleResponse).toList());
    }

    public RuleResponse getRule(Long id) {
        return toRuleResponse(requireRule(id));
    }

    @Transactional
    public RuleResponse createRule(RuleRequest req) {
        requireText(req.code(), "规则编码不能为空");
        requireText(req.name(), "规则名称不能为空");
        requireText(req.content(), "规则内容不能为空");
        if (ruleMapper.selectCount(new LambdaQueryWrapper<BusinessRuleEntity>()
                .eq(BusinessRuleEntity::getCode, req.code())) > 0) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "规则编码已存在: " + req.code());
        }
        BusinessRuleEntity e = new BusinessRuleEntity();
        e.setCode(req.code());
        e.setName(req.name());
        e.setRuleType(req.ruleType() == null ? "口径" : req.ruleType());
        e.setContent(req.content());
        e.setAppliesTo(JsonTextUtil.toJson(req.appliesTo()));
        e.setStatus(defaultActive(req.status()));
        LocalDateTime now = LocalDateTime.now();
        e.setCreatedAt(now);
        e.setUpdatedAt(now);
        ruleMapper.insert(e);
        log.info("knowledge_rule_created code={}", e.getCode());
        return toRuleResponse(e);
    }

    @Transactional
    public RuleResponse updateRule(Long id, RuleRequest req) {
        BusinessRuleEntity e = requireRule(id);
        if (req.name() != null) e.setName(req.name());
        if (req.ruleType() != null) e.setRuleType(req.ruleType());
        if (req.content() != null) e.setContent(req.content());
        if (req.appliesTo() != null) e.setAppliesTo(JsonTextUtil.toJson(req.appliesTo()));
        if (req.status() != null) e.setStatus(req.status());
        e.setUpdatedAt(LocalDateTime.now());
        ruleMapper.updateById(e);
        return toRuleResponse(e);
    }

    @Transactional
    public void deleteRule(Long id) {
        requireRule(id);
        ruleMapper.deleteById(id);
        log.info("knowledge_rule_deleted id={}", id);
    }

    // ==================== 分析主题 ====================

    public PageResult<TopicResponse> listTopics(String domain, String status, long page, long size) {
        Page<AnalysisTopicEntity> p = new Page<>(page, size);
        Page<AnalysisTopicEntity> result = topicMapper.selectPage(p,
                new LambdaQueryWrapper<AnalysisTopicEntity>()
                        .eq(domain != null && !domain.isBlank(), AnalysisTopicEntity::getDomain, domain)
                        .eq(status != null && !status.isBlank(), AnalysisTopicEntity::getStatus, status)
                        .orderByAsc(AnalysisTopicEntity::getId));
        return PageResult.of(result.getTotal(), page, size,
                result.getRecords().stream().map(this::toTopicResponse).toList());
    }

    public TopicResponse getTopic(Long id) {
        return toTopicResponse(requireTopic(id));
    }

    @Transactional
    public TopicResponse createTopic(TopicRequest req) {
        requireText(req.code(), "主题编码不能为空");
        requireText(req.name(), "主题名称不能为空");
        if (topicMapper.selectCount(new LambdaQueryWrapper<AnalysisTopicEntity>()
                .eq(AnalysisTopicEntity::getCode, req.code())) > 0) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "主题编码已存在: " + req.code());
        }
        AnalysisTopicEntity e = new AnalysisTopicEntity();
        e.setCode(req.code());
        e.setName(req.name());
        e.setDescription(req.description() == null ? "" : req.description());
        e.setDomain(req.domain() == null ? "" : req.domain());
        e.setRelatedObjectIds(JsonTextUtil.toJson(req.relatedObjectIds()));
        e.setRelatedMetricIds(JsonTextUtil.toJson(req.relatedMetricIds()));
        e.setStatus(defaultActive(req.status()));
        LocalDateTime now = LocalDateTime.now();
        e.setCreatedAt(now);
        e.setUpdatedAt(now);
        topicMapper.insert(e);
        log.info("knowledge_topic_created code={}", e.getCode());
        return toTopicResponse(e);
    }

    @Transactional
    public TopicResponse updateTopic(Long id, TopicRequest req) {
        AnalysisTopicEntity e = requireTopic(id);
        if (req.name() != null) e.setName(req.name());
        if (req.description() != null) e.setDescription(req.description());
        if (req.domain() != null) e.setDomain(req.domain());
        if (req.relatedObjectIds() != null) e.setRelatedObjectIds(JsonTextUtil.toJson(req.relatedObjectIds()));
        if (req.relatedMetricIds() != null) e.setRelatedMetricIds(JsonTextUtil.toJson(req.relatedMetricIds()));
        if (req.status() != null) e.setStatus(req.status());
        e.setUpdatedAt(LocalDateTime.now());
        topicMapper.updateById(e);
        return toTopicResponse(e);
    }

    @Transactional
    public void deleteTopic(Long id) {
        requireTopic(id);
        topicMapper.deleteById(id);
        log.info("knowledge_topic_deleted id={}", id);
    }

    // ==================== 知识图谱 ====================

    /**
     * 组装知识图谱：节点=对象/指标/规则/主题（业务编码为 id），
     * 边=主题—对象、主题—指标、规则→指标（评分点1 可视化载体）。
     */
    public GraphResponse buildGraph() {
        List<GraphNode> nodes = new ArrayList<>();
        List<GraphEdge> edges = new ArrayList<>();
        Set<String> nodeIds = new LinkedHashSet<>();

        List<BusinessObjectEntity> objects = objectMapper.selectList(
                new LambdaQueryWrapper<BusinessObjectEntity>()
                        .eq(BusinessObjectEntity::getStatus, "active"));
        for (BusinessObjectEntity o : objects) {
            nodes.add(new GraphNode(o.getCode(), "object", o.getName(), o.getDomain(),
                    o.getDescription(), null));
            nodeIds.add(o.getCode());
        }

        List<BusinessMetricEntity> metrics = metricMapper.selectList(
                new LambdaQueryWrapper<BusinessMetricEntity>()
                        .eq(BusinessMetricEntity::getStatus, "active"));
        for (BusinessMetricEntity m : metrics) {
            nodes.add(new GraphNode(m.getCode(), "metric", m.getName(), m.getDomain(),
                    m.getDescription(), m.getFormulaSql()));
            nodeIds.add(m.getCode());
        }

        List<BusinessRuleEntity> rules = ruleMapper.selectList(
                new LambdaQueryWrapper<BusinessRuleEntity>()
                        .eq(BusinessRuleEntity::getStatus, "active"));
        for (BusinessRuleEntity r : rules) {
            nodes.add(new GraphNode(r.getCode(), "rule", r.getName(), null,
                    r.getContent(), r.getRuleType()));
            nodeIds.add(r.getCode());
            for (String metricCode : JsonTextUtil.parseList(r.getAppliesTo())) {
                if (nodeIds.contains(metricCode)) {
                    edges.add(new GraphEdge(r.getCode(), metricCode, "rule_metric"));
                }
            }
        }

        List<AnalysisTopicEntity> topics = topicMapper.selectList(
                new LambdaQueryWrapper<AnalysisTopicEntity>()
                        .eq(AnalysisTopicEntity::getStatus, "active"));
        for (AnalysisTopicEntity t : topics) {
            nodes.add(new GraphNode(t.getCode(), "topic", t.getName(), t.getDomain(),
                    t.getDescription(), null));
            nodeIds.add(t.getCode());
            for (String objCode : JsonTextUtil.parseList(t.getRelatedObjectIds())) {
                if (nodeIds.contains(objCode)) {
                    edges.add(new GraphEdge(t.getCode(), objCode, "topic_object"));
                }
            }
            for (String metricCode : JsonTextUtil.parseList(t.getRelatedMetricIds())) {
                if (nodeIds.contains(metricCode)) {
                    edges.add(new GraphEdge(t.getCode(), metricCode, "topic_metric"));
                }
            }
        }

        return new GraphResponse(nodes, edges);
    }

    // ==================== 私有工具 ====================

    private BusinessObjectEntity requireObject(Long id) {
        BusinessObjectEntity e = objectMapper.selectById(id);
        if (e == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "业务对象不存在: " + id);
        return e;
    }

    private BusinessMetricEntity requireMetric(Long id) {
        BusinessMetricEntity e = metricMapper.selectById(id);
        if (e == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "业务指标不存在: " + id);
        return e;
    }

    private BusinessRuleEntity requireRule(Long id) {
        BusinessRuleEntity e = ruleMapper.selectById(id);
        if (e == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "业务规则不存在: " + id);
        return e;
    }

    private AnalysisTopicEntity requireTopic(Long id) {
        AnalysisTopicEntity e = topicMapper.selectById(id);
        if (e == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "分析主题不存在: " + id);
        return e;
    }

    private static void requireText(String value, String message) {
        if (value == null || value.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, message);
        }
    }

    private static String defaultActive(String status) {
        return (status == null || status.isBlank()) ? "active" : status;
    }

    private ObjectResponse toObjectResponse(BusinessObjectEntity e) {
        return new ObjectResponse(e.getId(), e.getCode(), e.getName(), e.getDescription(),
                e.getDomain(), e.getStatus(), e.getCreatedAt(), e.getUpdatedAt());
    }

    private MetricResponse toMetricResponse(BusinessMetricEntity e) {
        return new MetricResponse(e.getId(), e.getCode(), e.getName(), e.getDescription(),
                e.getFormulaSql(), e.getUnit(), e.getDomain(),
                JsonTextUtil.parseList(e.getSourceTables()),
                JsonTextUtil.parseList(e.getSourceColumns()),
                e.getStatus(), e.getCreatedAt(), e.getUpdatedAt());
    }

    private RuleResponse toRuleResponse(BusinessRuleEntity e) {
        return new RuleResponse(e.getId(), e.getCode(), e.getName(), e.getRuleType(),
                e.getContent(), JsonTextUtil.parseList(e.getAppliesTo()),
                e.getStatus(), e.getCreatedAt(), e.getUpdatedAt());
    }

    private TopicResponse toTopicResponse(AnalysisTopicEntity e) {
        return new TopicResponse(e.getId(), e.getCode(), e.getName(), e.getDescription(),
                e.getDomain(), JsonTextUtil.parseList(e.getRelatedObjectIds()),
                JsonTextUtil.parseList(e.getRelatedMetricIds()),
                e.getStatus(), e.getCreatedAt(), e.getUpdatedAt());
    }
}
