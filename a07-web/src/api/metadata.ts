// AI-assisted
/**
 * F3 数据资源中心 API（docs/api/README.md §2 · /api/metadata/**）。
 * password 仅出现在 POST/PUT 请求体与连通测试请求体，响应不回显（R3）。
 */
import http from './http'
import { unwrapData, unwrapList, unwrapPage, type PageResult } from './common'
import type {
  ColumnMetadataItem,
  ConnectionTestResult,
  DataSourceItem,
  DataSourceRequest,
  RefreshResult,
  RelationshipItem,
  TableMetadataItem,
} from '../types/metadata'

export async function listDataSources(
  query: { status?: string; page?: number; size?: number } = {},
): Promise<PageResult<DataSourceItem>> {
  const params: Record<string, string | number> = {
    page: query.page ?? 1,
    size: query.size ?? 50,
  }
  if (query.status && query.status.trim().length > 0) params.status = query.status.trim()
  const res = await http.get<unknown>('/api/metadata/datasources', { params })
  return unwrapPage<DataSourceItem>(res.data)
}

export async function getDataSource(id: number): Promise<DataSourceItem> {
  const res = await http.get<unknown>(`/api/metadata/datasources/${id}`)
  return unwrapData<DataSourceItem>(res.data)
}

export async function createDataSource(body: DataSourceRequest): Promise<DataSourceItem> {
  const res = await http.post<unknown>('/api/metadata/datasources', body)
  return unwrapData<DataSourceItem>(res.data)
}

export async function updateDataSource(id: number, body: DataSourceRequest): Promise<DataSourceItem> {
  const res = await http.put<unknown>(`/api/metadata/datasources/${id}`, body)
  return unwrapData<DataSourceItem>(res.data)
}

export async function deleteDataSource(id: number): Promise<void> {
  await http.delete(`/api/metadata/datasources/${id}`)
}

/**
 * 已落库数据源连通测试：POST /api/metadata/datasources/{id}/test
 * BUG-020：编辑态 password 留空时前端改调本接口，服务端解密 password_enc 后连接。
 */
export async function testDataSource(id: number): Promise<ConnectionTestResult> {
  const res = await http.post<unknown>(`/api/metadata/datasources/${id}/test`)
  return normalizeTestResult(unwrapData(res.data))
}

/**
 * 注册前 / 改密后连通测试（不落库）：POST /api/metadata/datasources/test
 * body 须含明文 password；编辑已有数据源且未改密请改用 testDataSource(id)。
 */
export async function testConnectionInfo(body: DataSourceRequest): Promise<ConnectionTestResult> {
  const res = await http.post<unknown>('/api/metadata/datasources/test', body)
  return normalizeTestResult(unwrapData(res.data))
}

export async function refreshDataSource(id: number): Promise<RefreshResult> {
  const res = await http.post<unknown>(`/api/metadata/datasources/${id}/refresh`)
  return normalizeRefreshResult(unwrapData(res.data))
}

export async function triggerReindex(): Promise<boolean> {
  const res = await http.post<unknown>('/api/metadata/reindex')
  return Boolean(unwrapData(res.data))
}

export async function listTables(query: {
  dataSourceId?: number
  tableName?: string
  page?: number
  size?: number
}): Promise<PageResult<TableMetadataItem>> {
  const params: Record<string, string | number> = {
    page: query.page ?? 1,
    size: query.size ?? 20,
  }
  if (query.dataSourceId != null) params.dataSourceId = query.dataSourceId
  if (query.tableName && query.tableName.trim().length > 0) params.tableName = query.tableName.trim()
  const res = await http.get<unknown>('/api/metadata/tables', { params })
  return unwrapPage<TableMetadataItem>(res.data)
}

export async function listColumns(query: {
  dataSourceId?: number
  tableName?: string
  page?: number
  size?: number
}): Promise<PageResult<ColumnMetadataItem>> {
  const params: Record<string, string | number> = {
    page: query.page ?? 1,
    size: query.size ?? 50,
  }
  if (query.dataSourceId != null) params.dataSourceId = query.dataSourceId
  if (query.tableName && query.tableName.trim().length > 0) params.tableName = query.tableName.trim()
  const res = await http.get<unknown>('/api/metadata/columns', { params })
  return unwrapPage<ColumnMetadataItem>(res.data)
}

export async function listRelationships(dataSourceId?: number): Promise<RelationshipItem[]> {
  const params: Record<string, string | number> = {}
  if (dataSourceId != null) params.dataSourceId = dataSourceId
  const res = await http.get<unknown>('/api/metadata/relationships', { params })
  return unwrapList<RelationshipItem>(res.data)
}

function normalizeTestResult(raw: unknown): ConnectionTestResult {
  const rec = (typeof raw === 'object' && raw !== null ? raw : {}) as Record<string, unknown>
  return {
    connected: rec.connected === true,
    message: typeof rec.message === 'string' && rec.message.length > 0 ? rec.message : rec.connected === true ? '连接成功' : '连接失败',
    tableCount: typeof rec.tableCount === 'number' ? rec.tableCount : null,
  }
}

function normalizeRefreshResult(raw: unknown): RefreshResult {
  const rec = (typeof raw === 'object' && raw !== null ? raw : {}) as Record<string, unknown>
  return {
    tableCount: typeof rec.tableCount === 'number' ? rec.tableCount : 0,
    columnCount: typeof rec.columnCount === 'number' ? rec.columnCount : 0,
    relationshipCount: typeof rec.relationshipCount === 'number' ? rec.relationshipCount : 0,
    reindexNotified: rec.reindexNotified === true,
    message: typeof rec.message === 'string' ? rec.message : '',
  }
}
