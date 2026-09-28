// AI-assisted
/**
 * S2 业务知识中心类型 —— docs/api/README.md §1（主控冻结契约）。
 * 字段名与 a07-server KnowledgeDtos.java 保持一致，前端只读契约，不擅自改名。
 */

export type KnowledgeResource = 'objects' | 'metrics' | 'rules' | 'topics'

export type GraphNodeType = 'object' | 'metric' | 'rule' | 'topic'

export type GraphEdgeRelation = 'topic_object' | 'topic_metric' | 'rule_metric'

/** 四资源共用基础字段。 */
export interface KnowledgeBase {
  id: number
  code: string
  name: string
  status: string
  createdAt: string | null
  updatedAt: string | null
}

export interface KnowledgeObject extends KnowledgeBase {
  description: string
  domain: string
}

export interface KnowledgeMetric extends KnowledgeObject {
  formulaSql: string
  unit: string
  sourceTables: string[]
  sourceColumns: string[]
}

export interface KnowledgeRule extends KnowledgeBase {
  ruleType: string
  content: string
  appliesTo: string[]
}

export interface KnowledgeTopic extends KnowledgeObject {
  relatedObjectIds: string[]
  relatedMetricIds: string[]
}

/** 列表行联合：视图按 resource 收窄展示字段。 */
export type KnowledgeItem = KnowledgeObject | KnowledgeMetric | KnowledgeRule | KnowledgeTopic

/** POST/PUT 请求体（响应体字段的子集；数组字段可选）。 */
export interface ObjectRequest {
  code: string
  name: string
  description?: string
  domain?: string
  status?: string
}

export interface MetricRequest extends ObjectRequest {
  formulaSql?: string
  unit?: string
  sourceTables?: string[]
  sourceColumns?: string[]
}

export interface RuleRequest {
  code: string
  name: string
  ruleType?: string
  content?: string
  appliesTo?: string[]
  status?: string
}

export interface TopicRequest extends ObjectRequest {
  relatedObjectIds?: string[]
  relatedMetricIds?: string[]
}

export type KnowledgeRequest = ObjectRequest | MetricRequest | RuleRequest | TopicRequest

export interface GraphNode {
  /** 业务编码（非数字 id），图边以此关联 */
  id: string
  type: GraphNodeType
  name: string
  domain?: string
  description?: string
  extra?: string
}

export interface GraphEdge {
  source: string
  target: string
  relation: GraphEdgeRelation
}

export interface GraphResponse {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export const RESOURCE_LABELS: Record<KnowledgeResource, string> = {
  objects: '业务对象',
  metrics: '业务指标',
  rules: '业务规则',
  topics: '分析主题',
}

export const GRAPH_NODE_TYPE_LABELS: Record<GraphNodeType, string> = {
  object: '对象',
  metric: '指标',
  rule: '规则',
  topic: '主题',
}

export const GRAPH_EDGE_RELATION_LABELS: Record<GraphEdgeRelation, string> = {
  topic_object: '主题-对象',
  topic_metric: '主题-指标',
  rule_metric: '规则-指标',
}

/** 业务域候选（a07-data 种子；筛选输入仍可自定义）。 */
export const DOMAIN_OPTIONS = ['生产', '质量', '设备', '库存'] as const

/** 状态候选（后端 defaultActive=active）。 */
export const STATUS_OPTIONS = ['active', 'inactive', 'draft'] as const
