// AI-assisted
/**
 * Agent 事件协议类型 —— docs/03-架构与模块设计.md §4 的前端侧契约锚点（T-007 Step 7.2）。
 *
 * 与引擎 a07-agent/app/schemas/{event,plan,result}.py 逐字段对应；字段命名保持契约原样
 * （snake_case 与 camelCase 混用是契约现状，勿"统一"改名，否则与 docs/api 变更纪律冲突）。
 * 契约变更须走 docs/04 §4 变更流程；本文件对前端是只读事实源。
 */
import type { EChartsOption } from 'echarts'

// ---------- 枚举（与 schemas/plan.py 的 Literal 一致） ----------

export type AnalysisTopic = 'production' | 'quality' | 'equipment' | 'inventory' | 'general'
export type ExecutionMode = 'sql' | 'python' | 'ml'
export type PlanChartType = 'line' | 'bar' | 'pie' | 'scatter' | 'table'

// ---------- 标准分析结果对象（docs/03 §4 / ADR-2，前端只渲染此对象） ----------

/** 行：列名 → 单元格值。引擎侧已归一化（Decimal→float、日期→ISO 字符串、NULL→null）。 */
export type ResultRow = Record<string, string | number | boolean | null>

/** 执行信息。内层字段保持契约规定的 camelCase（勿改 snake_case）。 */
export interface ExecutionInfo {
  durationMs: number
  rowCount: number
  dataSource: string
  truncated: boolean
}

/** 图表骨架（type 为 ECharts 类型名；字段映射由引擎 chart/builder.py 模板拼装）。 */
export interface ChartSpec {
  type: string
  x: string | null
  y: string[]
  series: unknown[]
}

/**
 * AnalysisPlan（docs/03 §3.3 A2 / §4 plan_ready 载荷，与 schemas/plan.py 一致）。
 * 用 type 别名而非 interface：使其获得隐式索引签名，可安全通过 pinia 状态类型收窄/转换。
 */
export type AnalysisPlan = {
  intent: string
  topic: AnalysisTopic | null
  tables: string[]
  metrics: string[]
  dimensions: string[]
  filters: string[]
  time_range: Record<string, unknown>
  execution_mode: ExecutionMode
  ml_task: Record<string, unknown> | null
  chart_type: PlanChartType | null
  expected_output: string
}

/** 标准分析结果对象（docs/03 §4 JSON 骨架，与 schemas/result.py 一致）。 */
export interface AnalysisResult {
  columns: string[]
  rows: ResultRow[]
  summary: Record<string, unknown>
  chart: ChartSpec | null
  insights: string[]
  warnings: string[]
  sql: string | null
  python_code: string | null
  execution_info: ExecutionInfo
}

/** token 用量（done 载荷附加元信息 tokensCost，引擎累计口径）。 */
export interface TokenUsage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

// ---------- SSE 事件载荷（docs/03 §4 事件表，逐行对应） ----------

export interface TaskStartedPayload {
  sessionId: string
  messageId: string
  question: string
}

/** step_started / step_finished 载荷：stepId, name（意图理解/知识检索/资源定位/生成SQL/…）, detail。 */
export interface StepEventPayload {
  stepId: string
  name: string
  detail?: string
}

export interface TextDeltaPayload {
  /** 增量文本（结论/报告流式） */
  delta: string
  index: number
}

export interface SqlGeneratedPayload {
  sql: string
  /** 自修复轮次（0 = 首次生成） */
  attempt: number
}

export interface SqlValidatedPayload {
  sql: string
  valid: boolean
  message: string
}

export interface SqlExecutingPayload {
  sql: string
}

export interface SqlCompletedPayload {
  sql: string
  elapsedMs: number
  rowCount: number
  truncated: boolean
}

export interface CodeGeneratedPayload {
  language: string
  code: string
}

/** table 事件：标准对象的 columns/rows（引擎已截 100）/total + 执行信息。 */
export interface TablePayload {
  columns: string[]
  rows: ResultRow[]
  total: number
  execution_info: ExecutionInfo
}

export interface ChartBuildingPayload {
  type?: string
}

/**
 * chart 事件载荷。
 * docs/03 §4 实现契约（T-005 回写）：`{chartType, option}`，前端取 `data.option`
 * 作为完整 ECharts option 传入 setOption。
 * 兼容说明：引擎 a07-agent/app/orchestrator/pipeline.py 当前实际发射字段为
 * `type/x/y/series/option`，前端对两种字段名做归一读取（详见 T-007 工单变更申请）。
 */
export interface ChartPayload {
  chartType?: string
  option?: EChartsOption
  /** 引擎当前实现字段（兼容读取） */
  type?: string
  x?: string | null
  y?: string[]
  series?: unknown[]
}

export interface ClarifyPayload {
  question: string
  options?: string[]
}

/** done 载荷 = 标准分析结果对象全字段 + tokensCost + durationMs（docs/03 §4 实现契约）。 */
export interface DonePayload extends AnalysisResult {
  tokensCost: TokenUsage
  durationMs: number
}

export interface ErrorPayload {
  code: string
  /** 用户可读 */
  message: string
  suggestion?: string
}

export interface EmptyPayload {
  [key: string]: unknown
}

// ---------- 建模（P2a / T-011/12：A7 统一 ML 任务契约，与 app/ml/contracts.py 逐字段对齐） ----------

/** 六算法字面量（contracts.py ModelType）。 */
export type ModelType =
  | 'linear_regression'
  | 'decision_tree'
  | 'random_forest'
  | 'logistic_regression'
  | 'kmeans'
  | 'isolation_forest'

/** 任务类型（contracts.py TaskType，由 modeler 依 model_type 与目标列解析）。 */
export type MlTaskType = 'regression' | 'classification' | 'clustering' | 'anomaly'

/** 单个特征贡献度（树模型 feature_importances_ / 其余 permutation_importance）。 */
export interface FeatureImportanceItem {
  name: string
  score: number
}

/** 建模结果图数据（plots 元素）：type 为 ECharts 类型名，data 形态随 type 变化（见 utils/mlcharts.ts）。 */
export interface MLPlot {
  type: string
  data: Record<string, unknown>
}

/**
 * ml_result 事件载荷 = MLResponse.model_dump() 全字段（snake_case）
 * + modeler.ml_payload() 的 camelCase 补充（taskId/modelType/taskType/featureImportance/predictionsSample/modelPath）。
 * 两组字段同值并存是契约现状（docs/03 §4），勿"统一"改名。
 */
export interface MLResultPayload {
  task_id: string
  model_type: string
  task_type: MlTaskType
  metrics: Record<string, unknown>
  feature_importance: FeatureImportanceItem[]
  plots: MLPlot[]
  predictions_sample: Record<string, unknown>[]
  explanation: string
  model_path: string | null
  warnings: string[]

  // camelCase 补充（ml_payload）
  taskId: string
  modelType: string
  taskType: MlTaskType
  featureImportance: FeatureImportanceItem[]
  predictionsSample: Record<string, unknown>[]
  modelPath: string | null
}

/** insight_generating 载荷（pipeline：reportId/topic/steps）。 */
export interface InsightGeneratingPayload {
  reportId?: string
  topic?: string
  steps?: number
}

/**
 * report 事件载荷（pipeline：`reportId=rid, markdown, topic, warnings`）。
 * docs/03 §4 载荷要点为"markdown 全文 + reportId"，topic/warnings 为引擎实际附加字段。
 */
export interface ReportPayload {
  reportId: string
  markdown: string
  topic?: string
  warnings?: string[]
}

/** POST /api/agent/ml/run 请求体 = 统一 MLRequest 契约 + question（记录用，可空）。 */
export interface MlRunRequest {
  model_type: ModelType
  features: string[]
  target: string | null
  parameters: Record<string, unknown>
  data_ref: string
  question?: string
}

// ---------- 事件联合类型与运行时白名单 ----------

export const SSE_EVENT_TYPES = [
  'task_started',
  'step_started',
  'step_finished',
  'plan_ready',
  'text_delta',
  'sql_generated',
  'sql_validated',
  'sql_executing',
  'sql_completed',
  'code_generated',
  'table',
  'chart_building',
  'chart',
  'ml_result',
  'insight_generating',
  'report',
  'clarify',
  'done',
  'error',
] as const

export type SseEventType = (typeof SSE_EVENT_TYPES)[number]

export function isSseEventType(value: string): value is SseEventType {
  return (SSE_EVENT_TYPES as readonly string[]).includes(value)
}

/** 事件名 → 载荷类型映射（契约白名单内的事件必须在此登记）。 */
export interface SSEPayloads {
  task_started: TaskStartedPayload
  step_started: StepEventPayload
  step_finished: StepEventPayload
  plan_ready: AnalysisPlan
  text_delta: TextDeltaPayload
  sql_generated: SqlGeneratedPayload
  sql_validated: SqlValidatedPayload
  sql_executing: SqlExecutingPayload
  sql_completed: SqlCompletedPayload
  code_generated: CodeGeneratedPayload
  table: TablePayload
  chart_building: ChartBuildingPayload
  chart: ChartPayload
  ml_result: MLResultPayload
  insight_generating: InsightGeneratingPayload
  report: ReportPayload
  clarify: ClarifyPayload
  done: DonePayload
  error: ErrorPayload
}

/** 判别联合：switch(event.type) 时 data 自动窄化为对应载荷类型。 */
export type AgentEvent = {
  [K in SseEventType]: { type: K; data: SSEPayloads[K] }
}[SseEventType]

// ---------- 分析请求（docs/03 §4：POST /api/agent/analyze 请求体，经 S4 代理） ----------

export interface HistoryMessage {
  role: string
  content: string
}

export interface AnalyzeRequest {
  sessionId: string
  messageId: string
  question: string
  history: HistoryMessage[]
  context?: { budget?: number; mode?: string }
}
