// AI-assisted
/**
 * 分析历史（S4 任务归档）API：会话不留痕问题的前端接入（BUG-028 / T-016 归档链路的 UI 侧）。
 * 后端契约：GET /api/tasks（分页列表）、GET /api/tasks/{id}（详情：task/planJson/steps/result）。
 */
import http from './http'
import type { AnalysisPlan } from '../types/agent'

export interface TaskSummary {
  id: number
  sessionId: string
  question: string
  status: string
  createdAt: string
  durationMs: number | null
  tokensCost: number | null
}

export interface TaskStep {
  name: string
  detail?: string | null
  startedAt?: string | null
  finishedAt?: string | null
}

/** 归档的标准分析结果对象（docs/03 §4，引擎 done 时存档）。 */
export interface ArchivedStandardResult {
  columns?: string[]
  rows?: Record<string, unknown>[]
  summary?: Record<string, unknown>
  chart?: {
    type?: string
    x?: string | null
    y?: string[]
    series?: unknown[]
    option?: unknown
  }
  insights?: string[]
  warnings?: string[]
  sql?: string | null
  python_code?: string | null
  execution_info?: {
    durationMs?: number
    rowCount?: number
    dataSource?: string
    truncated?: boolean
  }
  report?: string
  reportId?: string
}

export interface TaskDetail {
  task: TaskSummary
  planJson: AnalysisPlan | Record<string, unknown> | null
  steps: TaskStep[]
  result: {
    standardResultJson?: string | null
    standardResult?: ArchivedStandardResult | string | null
    reportMarkdown?: string | null
  } | null
}

interface PageResp<T> {
  code: number
  message: string
  data: { total: number; records: T[] }
}

/** 拉取分析历史（最新在前）。失败抛出由调用方提示。 */
export async function fetchTaskHistory(page = 1, size = 20): Promise<{ total: number; records: TaskSummary[] }> {
  const res = await http.get<PageResp<TaskSummary>>('/api/tasks', { params: { page, size } })
  const data = res.data?.data
  return { total: data?.total ?? 0, records: data?.records ?? [] }
}

function parseStandardResult(raw: unknown): ArchivedStandardResult | null {
  if (!raw) return null
  if (typeof raw === 'string') {
    try {
      return JSON.parse(raw) as ArchivedStandardResult
    } catch {
      return null
    }
  }
  return raw as ArchivedStandardResult
}

/** 拉取任务详情（含归档标准结果）。 */
export async function fetchTaskDetail(id: number): Promise<TaskDetail> {
  const res = await http.get<{ code: number; data: TaskDetail }>(`/api/tasks/${id}`)
  const data = res.data?.data
  if (!data) throw new Error('任务详情为空')
  if (data.result) {
    data.result.standardResult = parseStandardResult(data.result.standardResult)
  }
  return data
}
