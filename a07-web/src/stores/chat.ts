// AI-assisted
/**
 * 会话 store（T-007 Step 7.3/7.4 核心）：接收 api/sse.ts 解析出的事件并分发到消息流状态。
 *
 * 红线 R4：本 store 只存储/转发后端事件载荷，不生成、不伪造任何业务数据；
 * 唯一的"本地推导"是 UI 状态（步骤 running/finished、SQL 阶段链），其依据均为已收到的真实事件。
 */
import { defineStore } from 'pinia'
import { analyzeStream } from '../api/sse'
import type {
  AgentEvent,
  AnalysisPlan,
  ExecutionInfo,
  MLResultPayload,
  ReportPayload,
  ResultRow,
  TokenUsage,
} from '../types/agent'

// ---------- 消息流渲染模型 ----------

export type StepStatus = 'running' | 'finished'

export interface StepItem {
  stepId: string
  name: string
  detail: string
  status: StepStatus
}

export type SqlStage = 'generated' | 'validated' | 'invalid' | 'executing' | 'completed'

/** 一条 SQL 的生成→校验→执行状态链（全部由 sql_* 事件驱动）。 */
export interface SqlRun {
  sql: string
  attempt: number
  stage: SqlStage
  /** 最近一次校验的说明文本（来自 sql_validated 载荷） */
  message: string
  elapsedMs?: number
  rowCount?: number
  truncated?: boolean
}

export interface TableCard {
  id: number
  columns: string[]
  rows: ResultRow[]
  total: number
  executionInfo: ExecutionInfo
}

export interface ChartCardData {
  id: number
  chartType: string
  /**
   * ECharts option（后端 chart 事件 data.option 原样传递）。
   * 状态侧声明为 unknown：完整 EChartsOption 联合经 pinia 深度解包会失真；
   * 渲染边界（ChartCard.vue）再窄化为 EChartsOption 后调 setOption。
   */
  option: unknown
}

export interface ClarifyCard {
  question: string
  options: string[]
}

export interface ErrorCard {
  code: string
  message: string
  suggestion: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  /** user=问题原文；assistant=text_delta 增量拼接的结论文本 */
  text: string
  status: 'streaming' | 'done' | 'error' | 'aborted'
  steps: StepItem[]
  sqlRun: SqlRun | null
  tables: TableCard[]
  charts: ChartCardData[]
  /** ml_result 事件载荷（P2a：建模分支结果，P2a Task 14.5） */
  mlResults: MLResultPayload[]
  /** report 事件载荷（P2a：报告模式产物） */
  reports: ReportPayload[]
  clarify: ClarifyCard | null
  error: ErrorCard | null
  plan: AnalysisPlan | null
  /** done 事件带来的警示（截断/省略图表等，来自后端真实载荷） */
  warnings: string[]
  tokensCost: TokenUsage | null
  durationMs: number | null
  /** 本条分析开始时刻（本地时钟，毫秒）——UI 计时器用，非后端数据 */
  startedAt: number
  /** 是否已收到本条消息的第一个事件（任何类型）——控制"等待引擎事件"占位符 */
  gotFirstEvent: boolean
  /** 历史归档恢复的消息（BUG-028）：内容全部来自 /api/tasks/{id} 存档，非伪造（R4） */
  restored?: boolean
}

function uid(): string {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `id-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

function userMessage(text: string): ChatMessage {
  return {
    id: uid(),
    role: 'user',
    text,
    status: 'done',
    steps: [],
    sqlRun: null,
    tables: [],
    charts: [],
    mlResults: [],
    reports: [],
    clarify: null,
    error: null,
    plan: null,
    warnings: [],
    tokensCost: null,
    durationMs: null,
    startedAt: Date.now(),
    gotFirstEvent: true,
  }
}

/** 引擎未发射 step 事件时时间线为空属正常（产物事件会派生补显节点），不伪造步骤（R4）。 */
function emptyAssistantMessage(id: string): ChatMessage {
  return {
    id,
    role: 'assistant',
    text: '',
    status: 'streaming',
    steps: [],
    sqlRun: null,
    tables: [],
    charts: [],
    mlResults: [],
    reports: [],
    clarify: null,
    error: null,
    plan: null,
    warnings: [],
    tokensCost: null,
    durationMs: null,
    startedAt: Date.now(),
    gotFirstEvent: false,
  }
}

/**
 * 防御性派生（T-010 增强 1）：某阶段的产物事件已到达但该阶段没有任何 step 节点时，
 * 依据真实产物事件补显时间线节点，保证任何引擎实现下都有进度可看。
 * detail 注明"由产物事件补显"及真实载荷信息，不虚构内容（R4）；
 * 同名真实/派生节点已存在时不重复建节点，仅推进状态。
 */
function ensureStageNode(run: ChatMessage, stageName: string, detail: string, status: StepStatus = 'finished'): void {
  const existing = run.steps.find((s) => s.name === stageName)
  if (existing) {
    if (status === 'finished' && existing.status !== 'finished') {
      existing.status = 'finished'
      if (detail) existing.detail = detail
    }
    return
  }
  run.steps.push({ stepId: `derived:${stageName}`, name: stageName, detail, status })
}

/** 进行中的流控制器（store 单例，模块级持有，不入响应式 state）。 */
let activeController: AbortController | null = null

export const useChatStore = defineStore('chat', {
  state: () => ({
    messages: [] as ChatMessage[],
    sessionId: uid(),
    streaming: false,
    /** 每应用一个事件 +1，视图用它做"滚到底部"等轻量联动，避免深 watch */
    renderTick: 0,
  }),
  getters: {
    /** 最近一条带 plan 的 assistant 消息的规划（右 Drawer 数据源） */
    lastPlan(state): AnalysisPlan | null {
      for (let i = state.messages.length - 1; i >= 0; i -= 1) {
        const msg = state.messages[i]
        if (msg && msg.role === 'assistant' && msg.plan) return msg.plan
      }
      return null
    },
  },
  actions: {
    reset(): void {
      this.cancelStream()
      this.messages = []
      this.sessionId = uid()
      this.streaming = false
    },

    /** 用户发起一次分析：追加 user 气泡 + assistant 流式占位，消费 SSE 至结束。 */
    async ask(question: string): Promise<void> {
      const trimmed = question.trim()
      if (this.streaming || trimmed.length === 0) return
      this.messages.push(userMessage(trimmed))
      const run = emptyAssistantMessage(uid())
      this.messages.push(run)
      this.streaming = true
      this.renderTick += 1

      const controller = new AbortController()
      activeController = controller
      try {
        // P1 单轮：history 恒为空数组（契约字段保留，P2 多轮接入）
        await analyzeStream(
          { sessionId: this.sessionId, messageId: run.id, question: trimmed, history: [] },
          { signal: controller.signal, onEvent: (event) => this.applyEvent(run.id, event) },
        )
        if (run.status === 'streaming') {
          // 流结束但没收到 done/error 帧：连接异常中断，如实呈现（不冒充完成态，R4）
          run.status = 'error'
          run.error = {
            code: 'STREAM_CLOSED',
            message: '连接在分析完成前中断',
            suggestion: '请重新发起分析；若持续出现请联系管理员检查服务日志',
          }
        }
      } catch (err) {
        if (controller.signal.aborted) {
          run.status = 'aborted'
        } else {
          run.status = 'error'
          run.error = {
            code: 'REQUEST_FAILED',
            message: err instanceof Error ? err.message : '分析请求失败',
            suggestion: '请确认业务服务与分析引擎均已正常启动后重试',
          }
        }
      } finally {
        this.streaming = false
        activeController = null
        this.renderTick += 1
      }
    },

    /** 中止进行中的流（用户离开页面/退出登录时调用）。 */
    cancelStream(): void {
      activeController?.abort()
      activeController = null
    },

    /**
     * SSE 事件分发入口：switch 判别联合，event.data 自动窄化为对应载荷类型。
     *
     * 终态语义（T-010 增强 3）：done/error（及用户中止）到达后本条消息进入终态，
     * 忽略同一条消息后续到达的任何事件——防御历史引擎/异常序列覆盖已完成内容
     * （用户实测曾出现拒绝信息被后续表格覆盖）。
     */
    applyEvent(messageId: string, event: AgentEvent): void {
      const run = this.messages.find((m) => m.id === messageId && m.role === 'assistant')
      if (!run) return
      if (run.status !== 'streaming') {
        console.warn(`[chat] 消息 ${messageId} 已终态（${run.status}），忽略后续事件 ${event.type}`)
        return
      }
      // 任何类型的第一个事件都结束"等待引擎事件"占位态
      run.gotFirstEvent = true
      switch (event.type) {
        case 'task_started':
          // 载荷 sessionId/messageId/question 已在请求中，P1 无需额外渲染
          break
        case 'plan_ready':
          run.plan = event.data
          // 防御性派生：引擎未发"意图理解" step 时由 plan_ready 产物补显
          ensureStageNode(run, '意图理解', '由 plan_ready 产物事件补显：分析规划已生成')
          break
        case 'step_started': {
          // 真实事件与派生节点同名时收编复用（防重复节点，如引擎先发产物后补 step）
          const existing = run.steps.find((s) => s.name === event.data.name)
          if (existing) {
            existing.stepId = event.data.stepId
            existing.status = 'running'
            if (event.data.detail) existing.detail = event.data.detail
          } else {
            run.steps.push({
              stepId: event.data.stepId,
              name: event.data.name,
              detail: event.data.detail ?? '',
              status: 'running',
            })
          }
          break
        }
        case 'step_finished': {
          const step =
            run.steps.find((s) => s.stepId === event.data.stepId) ??
            run.steps.find((s) => s.name === event.data.name)
          if (step) {
            step.status = 'finished'
            if (event.data.detail) step.detail = event.data.detail
          } else {
            // 未收到 started 的 finished：按契约兜底为已完成步骤
            run.steps.push({
              stepId: event.data.stepId,
              name: event.data.name,
              detail: event.data.detail ?? '',
              status: 'finished',
            })
          }
          break
        }
        case 'text_delta':
          // 增量追加（T-010 确认：只追加，不整段重绘）
          run.text += event.data.delta
          // 防御性派生：首个结论片段即证明"生成结论"阶段已产出
          ensureStageNode(run, '生成结论', '由 text_delta 产物事件补显：结论片段已开始下发')
          break
        case 'sql_generated':
          run.sqlRun = {
            sql: event.data.sql,
            attempt: event.data.attempt,
            stage: 'generated',
            message: '',
          }
          ensureStageNode(
            run,
            '生成SQL',
            `由 sql_generated 产物事件补显（第 ${event.data.attempt + 1} 次生成）`,
          )
          break
        case 'sql_validated': {
          if (run.sqlRun) {
            run.sqlRun.sql = event.data.sql
            run.sqlRun.stage = event.data.valid ? 'validated' : 'invalid'
            run.sqlRun.message = event.data.message
          }
          ensureStageNode(
            run,
            '安全校验',
            event.data.valid ? '由 sql_validated 产物事件补显：校验通过' : `由 sql_validated 产物事件补显：${event.data.message}`,
          )
          break
        }
        case 'sql_executing':
          if (run.sqlRun) run.sqlRun.stage = 'executing'
          ensureStageNode(run, '执行', '由 sql_executing 产物事件补显：正在只读执行', 'running')
          break
        case 'sql_completed':
          if (run.sqlRun) {
            run.sqlRun.stage = 'completed'
            run.sqlRun.elapsedMs = event.data.elapsedMs
            run.sqlRun.rowCount = event.data.rowCount
            run.sqlRun.truncated = event.data.truncated
          }
          ensureStageNode(
            run,
            '执行',
            `由 sql_completed 产物事件补显：返回 ${event.data.rowCount} 行，耗时 ${event.data.elapsedMs}ms`,
          )
          break
        case 'table':
          run.tables.push({
            id: run.tables.length,
            columns: event.data.columns,
            rows: event.data.rows,
            total: event.data.total,
            executionInfo: event.data.execution_info,
          })
          // 兜底派生：引擎直接发 table 而无 sql_completed 时，执行阶段仍可见
          ensureStageNode(run, '执行', `由 table 产物事件补显：结果集 ${event.data.total} 行`)
          break
        case 'chart': {
          const option = event.data.option
          if (option) {
            run.charts.push({
              id: run.charts.length,
              chartType: event.data.chartType ?? event.data.type ?? '',
              option,
            })
            ensureStageNode(
              run,
              '生成图表',
              `由 chart 产物事件补显：已生成 ${event.data.chartType ?? event.data.type ?? ''} 图表`.trim(),
            )
          }
          break
        }
        case 'clarify':
          run.clarify = {
            question: event.data.question,
            options: event.data.options ?? [],
          }
          break
        case 'error':
          run.error = {
            code: event.data.code,
            message: event.data.message,
            suggestion: event.data.suggestion ?? '',
          }
          run.status = 'error' // 终态：此后同消息任何事件被忽略
          break
        case 'done':
          run.status = 'done' // 终态：此后同消息任何事件被忽略
          run.warnings = [...event.data.warnings]
          run.tokensCost = event.data.tokensCost
          run.durationMs = event.data.durationMs
          break
        case 'ml_result':
          // P2a：建模分支结果（载荷含 camelCase 补充字段，直接入列渲染）
          run.mlResults.push(event.data)
          break
        case 'report':
          run.reports.push({
            reportId: event.data.reportId,
            markdown: event.data.markdown,
            topic: event.data.topic,
            warnings: event.data.warnings ?? [],
          })
          break
        case 'chart_building':
        case 'code_generated':
        case 'insight_generating':
          // insight_generating 仅报告前置信号（载荷 reportId/topic/steps），P2a 不单独渲染
          break
      }
      this.renderTick += 1
    },

    /**
     * 从归档恢复一次历史分析到当前消息流（BUG-028：会话不留痕）。
     * 数据全部来自 /api/tasks/{id} 存档（task/planJson/steps/standardResult/reportMarkdown），
     * 归档缺失的部分如实缺省、不补造（红线 R4）。恢复后进入终态 done，不可再流式。
     */
    restoreFromArchive(detail: {
      task: { id: number; question: string; durationMs: number | null; createdAt: string }
      planJson: unknown
      steps: { name: string; detail?: string | null }[]
      result: { standardResult?: unknown; reportMarkdown?: string | null } | null
    }): boolean {
      if (this.streaming) return false
      const sr = (detail.result?.standardResult ?? null) as {
        columns?: string[]
        rows?: ResultRow[]
        chart?: { type?: string; x?: string | null; y?: string[]; series?: unknown[]; option?: unknown }
        insights?: string[]
        warnings?: string[]
        sql?: string | null
        python_code?: string | null
        execution_info?: { durationMs?: number; rowCount?: number; dataSource?: string; truncated?: boolean }
        report?: string
        reportId?: string
      } | null

      this.messages.push({ ...userMessage(detail.task.question) })

      const run = emptyAssistantMessage(uid())
      run.status = 'done'
      run.restored = true
      run.gotFirstEvent = true
      run.startedAt = Date.now()
      run.steps = (detail.steps ?? []).map((s, i) => ({
        stepId: `arch-${i + 1}`,
        name: s.name,
        detail: s.detail ?? '',
        status: 'finished' as const,
      }))
      if (detail.planJson && typeof detail.planJson === 'object') {
        run.plan = detail.planJson as AnalysisPlan
      }
      const exec = sr?.execution_info
      if (sr?.sql) {
        run.sqlRun = {
          sql: sr.sql,
          attempt: 1,
          stage: 'completed',
          message: '历史归档（已通过安全校验并执行）',
          elapsedMs: exec?.durationMs,
          rowCount: exec?.rowCount,
          truncated: exec?.truncated,
        }
      }
      if (sr?.columns && sr.columns.length > 0) {
        run.tables.push({
          id: Date.now(),
          columns: sr.columns,
          rows: sr.rows ?? [],
          total: exec?.rowCount ?? (sr.rows?.length ?? 0),
          executionInfo: {
            durationMs: exec?.durationMs ?? 0,
            rowCount: exec?.rowCount ?? (sr.rows?.length ?? 0),
            dataSource: exec?.dataSource ?? '历史归档',
            truncated: exec?.truncated ?? false,
          },
        })
      }
      // 图表：优先用归档的完整 option；仅有时可从 spec（type/x/y/series）重建基础 option，
      // series 缺数据时如实跳过图表卡（不伪造）。
      const spec = sr?.chart
      if (spec && typeof spec === 'object') {
        const option = (spec.option ?? null) as Record<string, unknown> | null
        if (option) {
          run.charts.push({ id: Date.now() + 1, chartType: spec.type ?? '', option })
        } else if (Array.isArray(spec.series) && spec.series.length > 0) {
          run.charts.push({
            id: Date.now() + 1,
            chartType: spec.type ?? '',
            option: {
              title: { text: detail.task.question },
              xAxis: spec.x ? { type: 'category', data: [] } : { type: 'value' },
              yAxis: { type: 'value' },
              tooltip: { trigger: 'axis' },
              series: spec.series,
            },
          })
        }
      }
      if (detail.result?.reportMarkdown) {
        run.reports.push({
          reportId: sr?.reportId ?? `arch-${detail.task.id}`,
          markdown: detail.result.reportMarkdown,
        })
      }
      run.text = Array.isArray(sr?.insights) ? sr.insights.filter(Boolean).join('\n') : ''
      run.warnings = Array.isArray(sr?.warnings) ? [...sr.warnings] : []
      run.durationMs = detail.task.durationMs
      this.messages.push(run)
      this.renderTick += 1
      return true
    },
  },
})
