// AI-assisted
/**
 * 统一响应体/分页载荷解析（docs/api/README.md §0：{code,message,data} + PageResult）。
 * 兼容「已解包 data」与「完整 ApiResult」两种形态，避免视图层重复判断。
 */

export interface PageResult<T> {
  records: T[]
  total: number
  page: number
  size: number
}

export interface ApiEnvelope<T> {
  code: number
  message: string
  data: T
}

export const EMPTY_PAGE: PageResult<never> = { records: [], total: 0, page: 1, size: 20 }

/** 从 axios 响应体中取出业务 data；若已是载荷本身则原样返回。 */
export function unwrapData<T>(raw: unknown): T {
  if (typeof raw !== 'object' || raw === null) return raw as T
  const rec = raw as Record<string, unknown>
  if ('code' in rec && 'data' in rec) {
    return rec.data as T
  }
  return raw as T
}

/** 归一化分页载荷；缺失字段时给空页，不抛错（调用方仍可展示错误态）。 */
export function unwrapPage<T>(raw: unknown): PageResult<T> {
  const payload = unwrapData<Partial<PageResult<T>> | null>(raw)
  if (typeof payload !== 'object' || payload === null) {
    return { ...EMPTY_PAGE } as PageResult<T>
  }
  const records = Array.isArray(payload.records) ? payload.records : []
  return {
    records,
    total: typeof payload.total === 'number' ? payload.total : records.length,
    page: typeof payload.page === 'number' ? payload.page : 1,
    size: typeof payload.size === 'number' ? payload.size : 20,
  }
}

/** 数组载荷归一化（relationships 等 List 直出接口）。 */
export function unwrapList<T>(raw: unknown): T[] {
  const payload = unwrapData<unknown>(raw)
  return Array.isArray(payload) ? (payload as T[]) : []
}

/** 数组字段序列化/反序列化：表单文本框 ↔ API 字符串数组。 */
export function splitCsv(text: string): string[] {
  return text
    .split(/[,,、\n]/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0)
}

export function joinCsv(list: string[] | null | undefined): string {
  return Array.isArray(list) ? list.join(', ') : ''
}
