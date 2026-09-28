// AI-assisted
/**
 * F2 业务知识中心 API（docs/api/README.md §1 · /api/knowledge/**）。
 * 四资源同构 CRUD + graph；JWT 由 http 拦截器统一携带。
 */
import http from './http'
import { unwrapData, unwrapPage, type PageResult } from './common'
import type {
  GraphResponse,
  KnowledgeItem,
  KnowledgeObject,
  KnowledgeMetric,
  KnowledgeRequest,
  KnowledgeResource,
  KnowledgeRule,
  KnowledgeTopic,
} from '../types/knowledge'

export interface KnowledgeListQuery {
  domain?: string
  status?: string
  page?: number
  size?: number
}

function buildListParams(resource: KnowledgeResource, query: KnowledgeListQuery): Record<string, string | number> {
  const params: Record<string, string | number> = {
    page: query.page ?? 1,
    size: query.size ?? 20,
  }
  // 契约：rules 无 domain 过滤（server 侧忽略该参数）；UI 亦不展示该筛选
  if (resource !== 'rules' && query.domain && query.domain.trim().length > 0) {
    params.domain = query.domain.trim()
  }
  if (query.status && query.status.trim().length > 0) {
    params.status = query.status.trim()
  }
  return params
}

export async function listKnowledge(
  resource: KnowledgeResource,
  query: KnowledgeListQuery = {},
): Promise<PageResult<KnowledgeItem>> {
  const res = await http.get<unknown>(`/api/knowledge/${resource}`, {
    params: buildListParams(resource, query),
  })
  return unwrapPage<KnowledgeItem>(res.data)
}

export async function getKnowledgeItem(
  resource: KnowledgeResource,
  id: number,
): Promise<KnowledgeItem> {
  const res = await http.get<unknown>(`/api/knowledge/${resource}/${id}`)
  return unwrapData<KnowledgeItem>(res.data)
}

export async function createKnowledgeItem(
  resource: KnowledgeResource,
  body: KnowledgeRequest,
): Promise<KnowledgeItem> {
  const res = await http.post<unknown>(`/api/knowledge/${resource}`, body)
  return unwrapData<KnowledgeItem>(res.data)
}

export async function updateKnowledgeItem(
  resource: KnowledgeResource,
  id: number,
  body: KnowledgeRequest,
): Promise<KnowledgeItem> {
  const res = await http.put<unknown>(`/api/knowledge/${resource}/${id}`, body)
  return unwrapData<KnowledgeItem>(res.data)
}

export async function deleteKnowledgeItem(resource: KnowledgeResource, id: number): Promise<void> {
  await http.delete(`/api/knowledge/${resource}/${id}`)
}

export async function fetchKnowledgeGraph(): Promise<GraphResponse> {
  const res = await http.get<unknown>('/api/knowledge/graph')
  const payload = unwrapData<Partial<GraphResponse> | null>(res.data)
  if (typeof payload !== 'object' || payload === null) {
    return { nodes: [], edges: [] }
  }
  return {
    nodes: Array.isArray(payload.nodes) ? payload.nodes : [],
    edges: Array.isArray(payload.edges) ? payload.edges : [],
  }
}

/** 类型守卫：用于按 tab 收窄 KnowledgeItem 字段展示。 */
export function asObjectItem(item: KnowledgeItem): KnowledgeObject {
  return item as KnowledgeObject
}
export function asMetricItem(item: KnowledgeItem): KnowledgeMetric {
  return item as KnowledgeMetric
}
export function asRuleItem(item: KnowledgeItem): KnowledgeRule {
  return item as KnowledgeRule
}
export function asTopicItem(item: KnowledgeItem): KnowledgeTopic {
  return item as KnowledgeTopic
}
