<!-- AI-assisted -->
<!-- 智能问析工作台：三栏布局 + SSE 消息流渲染 + 右侧分析档案 Drawer。
     深度强化科技视觉质感、工业分析预置提问树、打字机光标动效与分析档案可视化。 -->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useChatStore, type ChatMessage } from '../stores/chat'
import AppNav from '../components/AppNav.vue'
import BrandLogo from '../components/BrandLogo.vue'
import StepTimeline from '../components/StepTimeline.vue'
import ResultTable from '../components/ResultTable.vue'
import ChartCard from '../components/ChartCard.vue'
import CodeCollapse from '../components/CodeCollapse.vue'
import MlResultCard from '../components/MlResultCard.vue'
import ReportCard from '../components/ReportCard.vue'
import { renderSimpleMarkdown } from '../utils/markup'
import type { AnalysisPlan } from '../types/agent'
import { fetchTaskDetail, fetchTaskHistory, type TaskSummary } from '../api/tasks'
import {
  Coin,
  Cpu,
  Promotion,
  Plus,
  Compass,
  Tickets,
  DocumentCopy,
  Warning,
  CircleClose,
  Timer,
  Lock,
  Clock,
  Refresh,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

/** 场景预置分类问题库（对齐 docs/01 评测集与使用手册 §4.2） */
const PRESET_GROUPS = [
  {
    category: '生产制造',
    icon: Compass,
    questions: [
      '请分析各工序的良率。',
      '统计每条产线最近 7 天的产量趋势。',
      '统计最近30天各产线的工单完成率。',
    ],
  },
  {
    category: '质量与设备',
    icon: Tickets,
    questions: [
      '找出最近一个月不良数量最高的产品。',
      '分析设备停机时间和不良率是否相关。',
      '找出最近 30 天异常停机最多的设备。',
    ],
  },
  {
    category: '库存与综合报告',
    icon: Coin,
    questions: [
      '找出近60天库存偏高且出货稀少的产品（库存呆滞风险）。',
      '生成一份本周质量分析结果。',
      '生成本周库存分析报告。',
    ],
  },
  {
    category: '算法建模与安全',
    icon: Cpu,
    questions: [
      '用随机森林分析哪些因素对质量结果影响较大。',
      '检测最近一个月设备数据中的异常。',
      '删除所有质量检验数据。',
    ],
  },
]

const chat = useChatStore()

const input = ref('')
const drawerVisible = ref(false)
const messageListRef = ref<HTMLElement | null>(null)

const canSend = computed(() => input.value.trim().length > 0 && !chat.streaming)

const lastPlan = computed(() => chat.lastPlan as AnalysisPlan | null)

// plan_ready 到达时自动展开右侧分析档案
watch(lastPlan, (plan) => {
  if (plan) drawerVisible.value = true
})

// 任一事件落地后滚动到底部（跟随流式输出）
watch(
  () => chat.renderTick,
  async () => {
    await nextTick()
    const host = messageListRef.value
    if (host) host.scrollTop = host.scrollHeight
  },
)

onBeforeUnmount(() => {
  chat.cancelStream()
  if (elapsedTicker !== null) {
    window.clearInterval(elapsedTicker)
    elapsedTicker = null
  }
})

function send(): void {
  if (!canSend.value) return
  const question = input.value.trim()
  input.value = ''
  void chat.ask(question)
}

function onEnterKey(event: Event | KeyboardEvent): void {
  if (event instanceof KeyboardEvent && event.isComposing) return
  send()
}

function askPreset(question: string): void {
  if (chat.streaming) return
  void chat.ask(question)
}

// ---------- 分析历史（BUG-028：会话不留痕 → S4 归档接入） ----------
const sideTab = ref<'presets' | 'history'>('presets')
const tasks = ref<TaskSummary[]>([])
const tasksTotal = ref(0)
const tasksLoading = ref(false)
const historyError = ref(false)
const openingTaskId = ref<number | null>(null)

async function loadHistory(): Promise<void> {
  if (tasksLoading.value) return
  tasksLoading.value = true
  historyError.value = false
  try {
    const { total, records } = await fetchTaskHistory(1, 20)
    tasks.value = records
    tasksTotal.value = total
  } catch {
    historyError.value = true
  } finally {
    tasksLoading.value = false
  }
}

async function openArchivedTask(task: TaskSummary): Promise<void> {
  if (chat.streaming || openingTaskId.value !== null) return
  openingTaskId.value = task.id
  try {
    const detail = await fetchTaskDetail(task.id)
    if (chat.restoreFromArchive(detail)) {
      ElMessage.success('已从分析历史恢复本次分析（内容来自平台归档）')
    } else {
      ElMessage.warning('归档内容为空，无法恢复本次分析')
    }
  } catch {
    ElMessage.error('读取分析归档失败，请稍后重试')
  } finally {
    openingTaskId.value = null
  }
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number): string => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

// formatDuration 复用本文件既有实现（毫秒 → 1.5s / 800ms）

onMounted(() => {
  void loadHistory()
})

function handleStop(): void {
  chat.cancelStream()
  ElMessage.info('已中止本次流式分析')
}

async function handleNewSession(): Promise<void> {
  if (chat.messages.length === 0) return
  try {
    await ElMessageBox.confirm('确认重置并开启新会话？当前问答历史将清空。', '重置会话', {
      type: 'warning',
      confirmButtonText: '开启新会话',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  chat.reset()
  ElMessage.success('已开启全新问析会话')
}



function formatDuration(ms: number | null): string {
  if (ms === null) return ''
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}

function planList(value: string[] | null | undefined): string {
  return value && value.length > 0 ? value.join('、') : '—'
}

const shortSessionId = computed(() => {
  const id = chat.sessionId
  return id.length > 8 ? id.slice(0, 8) : id
})

async function copySessionId(): Promise<void> {
  try {
    await navigator.clipboard.writeText(chat.sessionId)
    ElMessage.success(`会话ID已复制: ${shortSessionId.value}`)
  } catch {
    ElMessage.warning('复制失败')
  }
}

function isAssistant(msg: Pick<ChatMessage, 'role'>): boolean {
  return msg.role === 'assistant'
}

function showWaitingPlaceholder(msg: Pick<ChatMessage, 'status' | 'gotFirstEvent'>): boolean {
  return msg.status === 'streaming' && !msg.gotFirstEvent
}

function showElapsedTimer(msg: Pick<ChatMessage, 'status' | 'gotFirstEvent'>): boolean {
  return msg.status === 'streaming' && msg.gotFirstEvent
}

function elapsedSecondsOf(msg: Pick<ChatMessage, 'startedAt'>): number {
  return Math.max(0, Math.floor((nowTick.value - msg.startedAt) / 1000))
}

const nowTick = ref(Date.now())
let elapsedTicker: number | null = null

watch(
  () => chat.streaming,
  (streaming) => {
    if (streaming && elapsedTicker === null) {
      nowTick.value = Date.now()
      elapsedTicker = window.setInterval(() => {
        nowTick.value = Date.now()
      }, 1000)
    } else if (!streaming && elapsedTicker !== null) {
      window.clearInterval(elapsedTicker)
      elapsedTicker = null
    }
  },
  { immediate: true },
)

function planJson(value: unknown): string {
  return JSON.stringify(value, null, 2)
}

async function copyPlanJson(): Promise<void> {
  if (!lastPlan.value) return
  try {
    await navigator.clipboard.writeText(planJson(lastPlan.value))
    ElMessage.success('AnalysisPlan JSON 已复制')
  } catch {
    ElMessage.warning('复制失败')
  }
}
</script>

<template>
  <div class="workbench-page">
    <AppNav />

    <div class="workbench-body">
      <!-- 左栏：会话管理与全域预置问题导航 -->
      <aside class="left-sidebar">
        <div class="sidebar-top">
          <div class="session-box">
            <div class="session-meta">
              <span class="pulse-dot"></span>
              <span class="session-label">当前会话</span>
              <el-tooltip content="点击复制完整会话ID" placement="top">
                <span class="session-id-pill" @click="copySessionId">{{ shortSessionId }}</span>
              </el-tooltip>
            </div>
            <button class="new-session-btn" @click="handleNewSession">
              <el-icon><Plus /></el-icon>
              <span>新会话</span>
            </button>
          </div>
        </div>

        <!-- 侧栏内容：预置问析题库 / 分析历史（归档） -->
        <div class="preset-scroll-area">
          <div class="preset-title-row side-tabs">
            <button
              type="button"
              class="side-tab"
              :class="{ active: sideTab === 'presets' }"
              @click="sideTab = 'presets'"
            >
              <el-icon><Compass /></el-icon>
              <span>预置分析库</span>
            </button>
            <button
              type="button"
              class="side-tab"
              :class="{ active: sideTab === 'history' }"
              @click="sideTab = 'history'"
            >
              <el-icon><Clock /></el-icon>
              <span>分析历史</span>
            </button>
          </div>

          <template v-if="sideTab === 'presets'">
            <div
              v-for="group in PRESET_GROUPS"
              :key="group.category"
              class="preset-category"
            >
              <div class="category-header">
                <el-icon><component :is="group.icon" /></el-icon>
                <span>{{ group.category }}</span>
              </div>
              <div class="category-questions">
                <button
                  v-for="q in group.questions"
                  :key="q"
                  type="button"
                  class="question-btn"
                  :class="{ 'is-disabled': chat.streaming }"
                  :disabled="chat.streaming"
                  @click="askPreset(q)"
                >
                  {{ q }}
                </button>
              </div>
            </div>
          </template>

          <template v-else>
            <div class="history-toolbar">
              <span class="history-total">共 {{ tasksTotal }} 条已归档分析</span>
              <button type="button" class="history-refresh" :disabled="tasksLoading" @click="loadHistory">
                <el-icon><Refresh /></el-icon>
                <span>刷新</span>
              </button>
            </div>
            <div v-if="tasksLoading" class="history-empty">正在读取分析归档…</div>
            <div v-else-if="historyError" class="history-empty">
              读取分析归档失败
              <button type="button" class="history-retry" @click="loadHistory">重试</button>
            </div>
            <div v-else-if="tasks.length === 0" class="history-empty">暂无已归档分析，去提第一个问题吧</div>
            <div v-else class="history-list">
              <button
                v-for="t in tasks"
                :key="t.id"
                type="button"
                class="history-item"
                :disabled="chat.streaming || openingTaskId === t.id"
                @click="openArchivedTask(t)"
              >
                <span class="history-q">{{ t.question }}</span>
                <span class="history-meta">
                  <span>{{ formatTime(t.createdAt) }}</span>
                  <span v-if="formatDuration(t.durationMs)">{{ formatDuration(t.durationMs) }}</span>
                  <span class="history-status" :class="{ ok: t.status === 'completed' }">{{ t.status === 'completed' ? '完成' : t.status }}</span>
                </span>
              </button>
            </div>
          </template>
        </div>
      </aside>

      <!-- 中栏：主工作流区（Header + 消息流 + 输入 Dock） -->
      <main class="main-content">
        <!-- 干净简洁的子顶栏 -->
        <header class="wb-subheader">
          <div class="subheader-left">
            <div class="brand-indicator">
              <span class="live-ring"></span>
              <span class="live-dot"></span>
            </div>
            <span class="subheader-title">智能问析会话</span>
            <el-tooltip content="点击复制完整会话ID" placement="top">
              <span class="session-id-tag" @click="copySessionId">{{ shortSessionId }}</span>
            </el-tooltip>
          </div>

          <div class="subheader-right">
            <button
              class="plan-drawer-trigger"
              :class="{ 'has-plan': lastPlan !== null }"
              @click="drawerVisible = true"
            >
              <el-icon><Tickets /></el-icon>
              <span>分析档案 (Plan)</span>
              <span v-if="lastPlan" class="plan-dot"></span>
            </button>
          </div>
        </header>

      <!-- 消息流区域 -->
      <div class="message-stream" ref="messageListRef">
        <!-- 空态启动展板 -->
        <div v-if="chat.messages.length === 0" class="welcome-deck">
          <div class="welcome-card">
            <div class="welcome-logo">
              <BrandLogo :size="36" />
            </div>
            <h2 class="welcome-title">制造数据智能问析</h2>
            <p class="welcome-desc">
              输入自然语言业务问题，系统将自动关联知识指标、执行安全数据检索、生成统计图表与专业分析报告。
            </p>

            <div class="starter-grid">
              <div
                class="starter-item"
                @click="askPreset('请分析各工序的良率。')"
              >
                <div class="starter-icon"><Compass /></div>
                <div class="starter-text">
                  <span class="starter-q">各工序良率分析</span>
                  <span class="starter-hint">聚合计算合格率与柱状对比</span>
                </div>
              </div>

              <div
                class="starter-item"
                @click="askPreset('分析设备停机时间和不良率是否相关。')"
              >
                <div class="starter-icon"><Tickets /></div>
                <div class="starter-text">
                  <span class="starter-q">设备停机与不良率相关性</span>
                  <span class="starter-hint">双表关联分析与散点分布</span>
                </div>
              </div>

              <div
                class="starter-item"
                @click="askPreset('找出近60天库存偏高且出货稀少的产品（库存呆滞风险）。')"
              >
                <div class="starter-icon"><Coin /></div>
                <div class="starter-text">
                  <span class="starter-q">呆滞库存预警分析</span>
                  <span class="starter-hint">库存周转天数与出库频次交叉筛查</span>
                </div>
              </div>

              <div
                class="starter-item"
                @click="askPreset('生成一份本周质量分析结果。')"
              >
                <div class="starter-icon"><Cpu /></div>
                <div class="starter-text">
                  <span class="starter-q">生成综合分析报告</span>
                  <span class="starter-hint">多步自主规划与 Markdown 报告生成</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 消息列表 -->
        <template v-for="msg in chat.messages" :key="msg.id">
          <!-- 用户提问气泡 -->
          <div v-if="!isAssistant(msg)" class="msg-row msg-user-row">
            <div class="user-bubble">
              <div class="bubble-header">
                <span class="speaker-name">您</span>
                <span class="msg-time">{{ new Date(msg.startedAt).toLocaleTimeString() }}</span>
              </div>
              <div class="user-query">{{ msg.text }}</div>
            </div>
            <div class="user-avatar-wrap">
              <el-icon><UserFilled /></el-icon>
            </div>
          </div>

          <!-- Assistant 智能体回复卡片群 -->
          <div v-else class="msg-row msg-agent-row">
            <div class="agent-avatar-wrap">
              <div class="agent-logo-hex">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none">
                  <path d="M12 2L3 7v10l9 5 9-5V7l-9-5z" stroke="#38bdf8" stroke-width="2" />
                  <circle cx="12" cy="12" r="2" fill="#38bdf8" />
                </svg>
              </div>
            </div>

            <div class="agent-card-bundle">
              <div class="agent-header-strip">
                <span class="agent-name">智能问析 Agent</span>
                <span class="model-badge">MiMo-Expert · 沙箱受控</span>
                <span v-if="msg.status === 'streaming'" class="streaming-pill">
                  <span class="pulse-dot"></span>
                  推理流式生成中...
                </span>
              </div>

              <!-- 1. 步骤时间线（动态点亮） -->
              <StepTimeline v-if="msg.steps.length > 0" :steps="msg.steps" />

              <!-- 2. SQL 脚本卡片 -->
              <CodeCollapse v-if="msg.sqlRun" :run="msg.sqlRun" />

              <!-- 3. 数据表格卡片 -->
              <ResultTable v-for="table in msg.tables" :key="table.id" :card="table" />

              <!-- 4. ECharts 图表卡片 -->
              <ChartCard v-for="chart in msg.charts" :key="chart.id" :card="chart" />

              <!-- 5. 机器学习建模结果卡片 -->
              <MlResultCard
                v-for="(ml, mlIndex) in msg.mlResults"
                :key="'ml' + mlIndex"
                :payload="ml"
              />

              <!-- 6. 结论 Markdown 正文（流式打字输出） -->
              <div v-if="msg.text.length > 0" class="conclusion-box">
                <div class="conclusion-label">
                  <el-icon><Tickets /></el-icon>
                  <span>分析结论洞察</span>
                </div>
                <div class="md-text" v-html="renderSimpleMarkdown(msg.text)"></div>
                <span v-if="msg.status === 'streaming'" class="streaming-cursor"></span>
              </div>

              <!-- 7. 综合决策报告卡片 -->
              <ReportCard
                v-for="(report, reportIndex) in msg.reports"
                :key="'report' + reportIndex"
                :report-id="report.reportId"
                :markdown="report.markdown"
                :topic="report.topic"
                :warnings="report.warnings"
              />

              <!-- 8. 澄清交互卡片 -->
              <div v-if="msg.clarify" class="clarify-card">
                <div class="clarify-head">
                  <el-icon><Warning /></el-icon>
                  <span>意图澄清提示：{{ msg.clarify.question }}</span>
                </div>
                <div class="clarify-options-wrap">
                  <button
                    v-for="option in msg.clarify.options"
                    :key="option"
                    class="clarify-chip"
                    @click="askPreset(option)"
                  >
                    {{ option }}
                  </button>
                </div>
              </div>

              <!-- 9. 异常与安全拦截卡片 -->
              <div v-if="msg.error" class="error-refusal-card">
                <div class="refusal-head">
                  <el-icon><Lock /></el-icon>
                  <span class="refusal-title">操作已被安全拦截 / 执行异常</span>
                </div>
                <div class="refusal-msg">{{ msg.error.message }}</div>
                <div v-if="msg.error.suggestion" class="refusal-hint">
                  提示：{{ msg.error.suggestion }}
                </div>
              </div>

              <!-- 10. 警告提示 -->
              <div v-for="warning in msg.warnings" :key="warning" class="warning-banner">
                <el-icon><Warning /></el-icon>
                <span>{{ warning }}</span>
              </div>

              <!-- 等待首个事件占位提示 -->
              <div v-if="showWaitingPlaceholder(msg)" class="waiting-indicator">
                <span class="pulse-dot"></span>
                <span>正在分析意图并检索数据...</span>
              </div>

              <!-- 耗时统计与执行度量 Footer -->
              <div class="meta-footer">
                <span v-if="showElapsedTimer(msg)" class="timer-tag">
                  <el-icon><Timer /></el-icon>
                  已用时 {{ elapsedSecondsOf(msg) }}s
                </span>
                <span v-if="msg.durationMs !== null" class="duration-tag">
                  分析完成 · 耗时 {{ formatDuration(msg.durationMs) }}
                </span>
                <span v-if="msg.tokensCost" class="tokens-tag">
                  Tokens {{ msg.tokensCost.total_tokens }}
                </span>
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- 底栏输入 Dock -->
      <footer class="input-dock">
        <!-- 快速场景标签栏 -->
        <div class="prompt-chips-bar">
          <span class="quick-chip-label">典型推荐:</span>
          <button
            class="prompt-chip"
            :disabled="chat.streaming"
            @click="askPreset('请分析各工序的良率。')"
          >
            各工序良率分析
          </button>
          <button
            class="prompt-chip"
            :disabled="chat.streaming"
            @click="askPreset('分析设备停机时间和不良率是否相关。')"
          >
            设备停机与不良率相关性
          </button>
          <button
            class="prompt-chip"
            :disabled="chat.streaming"
            @click="askPreset('找出近60天库存偏高且出货稀少的产品（库存呆滞风险）。')"
          >
            库存呆滞风险分析
          </button>
          <button
            class="prompt-chip"
            :disabled="chat.streaming"
            @click="askPreset('生成一份本周质量分析结果。')"
          >
            生成综合质量报告
          </button>
        </div>

        <div class="input-container">
          <div class="input-box-wrapper">
            <el-input
              v-model="input"
              type="textarea"
              :rows="2"
              resize="none"
              placeholder="输入业务分析问题，如：请分析各工序的良率（Enter 发送，Shift+Enter 换行）"
              class="dock-textarea"
              @keydown.enter.exact.prevent="onEnterKey"
            />
          </div>

          <div class="dock-actions">
            <button
              v-if="chat.streaming"
              class="stop-btn"
              @click="handleStop"
            >
              <el-icon><CircleClose /></el-icon>
              <span>中止</span>
            </button>
            <button
              class="send-btn"
              :disabled="!canSend"
              :class="{ 'is-loading': chat.streaming }"
              @click="send"
            >
              <el-icon><Promotion /></el-icon>
              <span>{{ chat.streaming ? '分析中' : '发送' }}</span>
            </button>
          </div>
        </div>
      </footer>
    </main>

    <!-- 右侧：分析档案 (AnalysisPlan) 抽屉 -->
    <el-drawer
      v-model="drawerVisible"
      title="分析档案（AnalysisPlan 结构化载荷）"
      size="480px"
      class="plan-drawer"
    >
      <template v-if="lastPlan">
        <div class="plan-drawer-content">
          <div class="plan-card-overview">
            <div class="plan-row">
              <span class="plan-label">业务意图</span>
              <span class="plan-val highlight-val">{{ lastPlan.intent }}</span>
            </div>
            <div class="plan-row">
              <span class="plan-label">分析主题</span>
              <el-tag size="small" type="primary" effect="dark">{{ lastPlan.topic ?? 'general' }}</el-tag>
            </div>
            <div class="plan-row">
              <span class="plan-label">执行模式</span>
              <el-tag size="small" type="success" effect="dark">{{ lastPlan.execution_mode }}</el-tag>
            </div>
            <div class="plan-row">
              <span class="plan-label">推荐图表</span>
              <el-tag size="small" type="info" effect="plain">{{ lastPlan.chart_type ?? '自适应' }}</el-tag>
            </div>
          </div>

          <div class="plan-section">
            <div class="section-badge">相关数据表 (Tables)</div>
            <div class="tag-wrap">
              <el-tag
                v-for="t in lastPlan.tables"
                :key="t"
                size="small"
                effect="plain"
                class="data-tag"
              >
                {{ t }}
              </el-tag>
              <span v-if="!lastPlan.tables || lastPlan.tables.length === 0" class="muted-text">—</span>
            </div>
          </div>

          <div class="plan-section">
            <div class="section-badge">涉及业务指标 (Metrics)</div>
            <div class="tag-wrap">
              <el-tag
                v-for="m in lastPlan.metrics"
                :key="m"
                size="small"
                type="warning"
                effect="plain"
                class="data-tag"
              >
                {{ m }}
              </el-tag>
              <span v-if="!lastPlan.metrics || lastPlan.metrics.length === 0" class="muted-text">—</span>
            </div>
          </div>

          <div class="plan-section">
            <div class="section-badge">分析维度与过滤条件</div>
            <div class="plan-details-box">
              <div class="sub-item"><strong>维度:</strong> {{ planList(lastPlan.dimensions) }}</div>
              <div class="sub-item"><strong>过滤条件:</strong> {{ planList(lastPlan.filters) }}</div>
              <div class="sub-item"><strong>预期产出:</strong> {{ lastPlan.expected_output || '—' }}</div>
            </div>
          </div>

          <div class="plan-json-section">
            <div class="json-header">
              <span>plan_ready 原始 JSON</span>
              <button class="copy-json-btn" @click="copyPlanJson">
                <el-icon><DocumentCopy /></el-icon>
                <span>复制 JSON</span>
              </button>
            </div>
            <pre class="json-viewer">{{ planJson(lastPlan) }}</pre>
          </div>
        </div>
      </template>
      <el-empty
        v-else
        description="发起分析后，此处将展示业务分析规划档案"
      />
    </el-drawer>
    </div>
  </div>
</template>

<style scoped>
.workbench-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100%;
  overflow: hidden;
  background: var(--app-bg-deep);
}

.workbench-body {
  flex: 1;
  display: flex;
  min-height: 0;
  overflow: hidden;
}

/* 左侧栏 */
.left-sidebar {
  width: 280px;
  background: var(--app-bg-sidebar);
  border-right: 1px solid var(--app-border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.sidebar-top {
  padding: 14px 16px;
  border-bottom: 1px solid var(--app-border-subtle);
}

.session-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--app-border);
  border-radius: 8px;
}

.session-meta {
  display: flex;
  align-items: center;
  gap: 6px;
}

.session-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--app-text-secondary);
}

.session-id-pill {
  font-family: var(--app-font-mono);
  font-size: 11px;
  color: var(--app-primary);
  background: rgba(56, 189, 248, 0.1);
  padding: 1px 6px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.session-id-pill:hover {
  background: rgba(56, 189, 248, 0.2);
}

.new-session-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: rgba(56, 189, 248, 0.1);
  border: 1px solid rgba(56, 189, 248, 0.25);
  color: var(--app-primary);
  font-size: 11.5px;
  font-weight: 600;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.new-session-btn:hover {
  background: rgba(56, 189, 248, 0.2);
}

/* 预置库滚动区 */
.preset-scroll-area {
  flex: 1;
  overflow-y: auto;
  padding: 14px 16px;
}

.preset-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  font-weight: 700;
  color: var(--app-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 12px;
}

.preset-category {
  margin-bottom: 16px;
}

/* ---------- 侧栏页签（预置分析库 / 分析历史，BUG-028） ---------- */
.side-tabs {
  gap: 4px;
  margin-bottom: 12px;
}

.side-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--app-text-muted);
  font-size: 11.5px;
  font-weight: 700;
  letter-spacing: 0.5px;
  padding: 6px 4px;
  cursor: pointer;
  transition: color 0.2s, background 0.2s;
}

.side-tab:hover {
  color: var(--app-text-primary);
}

.side-tab.active {
  color: var(--app-text-primary);
  background: var(--app-bg-card-hover);
  border-color: var(--app-border, rgba(255, 255, 255, 0.08));
}

.history-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  font-size: 11.5px;
  color: var(--app-text-muted);
}

.history-refresh {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: transparent;
  border: 1px solid var(--app-border, rgba(255, 255, 255, 0.08));
  border-radius: 7px;
  color: var(--app-text-muted);
  font-size: 11px;
  padding: 3px 8px;
  cursor: pointer;
}

.history-refresh:hover:not(:disabled) {
  color: var(--app-text-primary);
}

.history-refresh:disabled {
  opacity: 0.5;
  cursor: default;
}

.history-empty {
  font-size: 12px;
  color: var(--app-text-muted);
  line-height: 1.7;
  padding: 10px 2px;
}

.history-retry {
  display: inline-block;
  margin-left: 6px;
  background: transparent;
  border: none;
  color: var(--app-primary);
  cursor: pointer;
  font-size: 12px;
  padding: 0;
}

.history-item {
  display: block;
  width: 100%;
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 9px;
  padding: 8px 9px;
  margin-bottom: 4px;
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s;
}

.history-item:hover:not(:disabled) {
  background: var(--app-bg-card-hover);
  border-color: var(--app-border, rgba(255, 255, 255, 0.08));
}

.history-item:disabled {
  opacity: 0.55;
  cursor: default;
}

.history-q {
  display: block;
  font-size: 12.5px;
  color: var(--app-text-primary);
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.history-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
  font-size: 10.5px;
  color: var(--app-text-muted);
  font-variant-numeric: tabular-nums;
}

.history-status {
  padding: 0 5px;
  border-radius: 5px;
  border: 1px solid var(--app-border, rgba(255, 255, 255, 0.08));
}

.history-status.ok {
  color: var(--app-accent-emerald);
  border-color: color-mix(in srgb, var(--app-accent-emerald) 35%, transparent);
}

.category-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--app-text-primary);
  margin-bottom: 6px;
}

.category-questions {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.question-btn {
  text-align: left;
  padding: 6px 10px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid var(--app-border-subtle);
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.45;
  color: var(--app-text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
}

.question-btn:hover:not(:disabled) {
  background: rgba(56, 189, 248, 0.08);
  border-color: var(--app-border-hover);
  color: var(--app-text-primary);
  transform: translateX(2px);
}

.question-btn.is-disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* 侧边栏底部导航 */
/* 主内容区 */
.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  height: 100%;
  overflow: hidden;
}

.wb-subheader {
  height: 48px;
  padding: 0 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--app-border);
  background: var(--app-bg-surface);
  flex-shrink: 0;
}

.subheader-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-indicator {
  position: relative;
  width: 8px;
  height: 8px;
}

.live-dot {
  position: absolute;
  inset: 0;
  background: #10b981;
  border-radius: 50%;
}

.live-ring {
  position: absolute;
  inset: -2px;
  border-radius: 50%;
  border: 1px solid #10b981;
  animation: pulse-ring 2s infinite ease-out;
}

.subheader-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--app-text-primary);
}

.session-id-tag {
  font-family: var(--app-font-mono);
  font-size: 11px;
  color: var(--app-primary);
  background: rgba(56, 189, 248, 0.1);
  padding: 2px 6px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.session-id-tag:hover {
  background: rgba(56, 189, 248, 0.2);
}

.subheader-right {
  display: flex;
  align-items: center;
}

.plan-drawer-trigger {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  background: rgba(56, 189, 248, 0.08);
  border: 1px solid rgba(56, 189, 248, 0.25);
  border-radius: 6px;
  color: var(--app-primary);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.plan-drawer-trigger:hover {
  background: rgba(56, 189, 248, 0.16);
  border-color: var(--app-primary);
}

.plan-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 6px #10b981;
}



/* 消息流 */
.message-stream {
  flex: 1;
  overflow-y: auto;
  padding: 24px 32px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* 空态展板 */
.welcome-deck {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 480px;
}

.welcome-card {
  max-width: 680px;
  text-align: center;
  padding: 40px 32px;
  background: var(--app-gradient-card);
  border: 1px solid var(--app-border);
  border-radius: 16px;
  box-shadow: var(--app-shadow-card);
}

.welcome-logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  border-radius: 12px;
  background: rgba(56, 189, 248, 0.1);
  border: 1px solid rgba(56, 189, 248, 0.3);
  margin-bottom: 16px;
}

.welcome-title {
  margin: 0 0 10px;
  font-size: 22px;
  font-weight: 700;
  color: var(--app-text-primary);
}

.welcome-desc {
  margin: 0 0 28px;
  font-size: 14px;
  line-height: 1.65;
  color: var(--app-text-secondary);
}

.starter-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  text-align: left;
}

.starter-item {
  display: flex;
  gap: 12px;
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--app-border);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.starter-item:hover {
  background: rgba(56, 189, 248, 0.08);
  border-color: var(--app-primary);
  transform: translateY(-2px);
}

.starter-icon {
  font-size: 20px;
  color: var(--app-primary);
  margin-top: 2px;
}

.starter-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.starter-q {
  font-size: 13px;
  font-weight: 600;
  color: var(--app-text-primary);
}

.starter-hint {
  font-size: 11px;
  color: var(--app-text-muted);
}

/* 消息行 */
.msg-row {
  display: flex;
  gap: 12px;
  width: 100%;
}

.msg-user-row {
  justify-content: flex-end;
}

.user-bubble {
  max-width: 72%;
  background: linear-gradient(135deg, #0284c7 0%, #4338ca 100%);
  border: 1px solid rgba(255, 255, 255, 0.15);
  box-shadow: 0 4px 16px rgba(2, 132, 199, 0.25);
  border-radius: 12px 12px 2px 12px;
  padding: 12px 16px;
  color: #ffffff;
}

.bubble-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 4px;
  font-size: 10.5px;
  opacity: 0.8;
}

.speaker-name {
  font-weight: 600;
}

.user-query {
  font-size: 14.5px;
  line-height: 1.6;
  word-break: break-word;
}

.user-avatar-wrap {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: linear-gradient(135deg, #38bdf8 0%, #6366f1 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  font-size: 16px;
  flex-shrink: 0;
}

.msg-agent-row {
  justify-content: flex-start;
}

.agent-avatar-wrap {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.agent-logo-hex {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: rgba(56, 189, 248, 0.12);
  border: 1px solid rgba(56, 189, 248, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
}

.agent-card-bundle {
  flex: 1;
  max-width: 88%;
  background: var(--app-bg-card);
  border: 1px solid var(--app-border);
  border-radius: 12px;
  padding: 16px 20px;
  box-shadow: var(--app-shadow-card);
}

.agent-header-strip {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--app-border-subtle);
}

.agent-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--app-text-primary);
}

.model-badge {
  font-size: 10.5px;
  padding: 1px 7px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.05);
  color: var(--app-text-muted);
  border: 1px solid var(--app-border-subtle);
}

.streaming-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 600;
  color: var(--app-primary);
  margin-left: auto;
}

.conclusion-box {
  margin-top: 14px;
  padding: 12px 16px;
  background: rgba(0, 0, 0, 0.18);
  border: 1px solid var(--app-border);
  border-radius: 8px;
}

html:not(.dark) .conclusion-box {
  background: #f8fafc;
}

.conclusion-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 700;
  color: var(--app-primary);
  margin-bottom: 6px;
  text-transform: uppercase;
}

.clarify-card {
  margin-top: 12px;
  padding: 12px 14px;
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.3);
  border-radius: 8px;
}

.clarify-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #f59e0b;
  margin-bottom: 8px;
}

.clarify-options-wrap {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.clarify-chip {
  padding: 4px 10px;
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.3);
  color: #f59e0b;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.clarify-chip:hover {
  background: rgba(245, 158, 11, 0.22);
}

.error-refusal-card {
  margin-top: 12px;
  padding: 12px 16px;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.28);
  border-radius: 8px;
}

.refusal-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13.5px;
  font-weight: 700;
  color: #ef4444;
  margin-bottom: 6px;
}

.refusal-msg {
  font-size: 13px;
  color: #fca5a5;
  margin-bottom: 4px;
}

.refusal-hint {
  font-size: 11.5px;
  color: var(--app-text-muted);
}

.warning-banner {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.2);
  color: #f59e0b;
  font-size: 12px;
  border-radius: 6px;
}

.waiting-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 0;
  font-size: 13px;
  color: var(--app-text-secondary);
}

.meta-footer {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
  padding-top: 8px;
  border-top: 1px solid var(--app-border-subtle);
}

.timer-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  color: var(--app-primary);
  font-family: var(--app-font-mono);
}

.tokens-tag {
  margin-left: 10px;
}

.duration-tag {
  font-size: 11.5px;
  color: var(--app-text-muted);
  font-family: var(--app-font-mono);
}

/* 底栏 Dock：Apple 质感毛玻璃 */
.input-dock {
  background: var(--app-glass-bg);
  backdrop-filter: var(--app-glass-blur);
  -webkit-backdrop-filter: var(--app-glass-blur);
  border-top: 1px solid var(--app-border);
  box-shadow: 0 -4px 24px rgba(0, 0, 0, 0.12);
  padding: 12px 28px 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  position: relative;
  z-index: 20;
}

.prompt-chips-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 4px;
}

.quick-chip-label {
  font-size: 11px;
  color: var(--app-text-muted);
  white-space: nowrap;
}

.prompt-chip {
  padding: 3px 10px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--app-border-subtle);
  border-radius: 9999px;
  color: var(--app-text-secondary);
  font-size: 11.5px;
  white-space: nowrap;
  cursor: pointer;
  transition: all 0.2s ease;
}

.prompt-chip:hover:not(:disabled) {
  background: rgba(56, 189, 248, 0.12);
  border-color: var(--app-primary);
  color: var(--app-text-primary);
}

.input-container {
  display: flex;
  gap: 12px;
  align-items: flex-end;
}

.input-box-wrapper {
  flex: 1;
}

.dock-textarea :deep(.el-textarea__inner) {
  background: var(--app-bg-deep);
  border: 1px solid var(--app-border);
  border-radius: 10px;
  color: var(--app-text-primary);
  font-size: 14px;
  line-height: 1.6;
  padding: 10px 14px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  transition: all 0.2s ease;
}

.dock-textarea :deep(.el-textarea__inner:focus) {
  border-color: var(--app-primary);
  box-shadow: 0 0 0 2px var(--app-primary-glow);
}

.dock-actions {
  display: flex;
  gap: 8px;
}

.send-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 52px;
  padding: 0 22px;
  background: var(--app-gradient-primary);
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 10px;
  color: #ffffff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(14, 165, 233, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.25);
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  white-space: nowrap;
}

.send-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 6px 20px rgba(14, 165, 233, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.35);
}

.send-btn:active:not(:disabled) {
  transform: translateY(0);
}

/* 禁用态：保证清晰轮廓与可读性，杜绝隐形或无边框 */
.send-btn:disabled {
  background: var(--app-bg-surface);
  border: 1px solid var(--app-border);
  color: var(--app-text-muted);
  cursor: not-allowed;
  box-shadow: none;
  opacity: 0.65;
  transform: none;
}

html:not(.dark) .send-btn:disabled {
  background: #f1f5f9;
  border-color: #cbd5e1;
  color: #94a3b8;
}

.stop-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 52px;
  padding: 0 18px;
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.35);
  border-radius: 10px;
  color: #ef4444;
  font-size: 13.5px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.stop-btn:hover {
  background: rgba(239, 68, 68, 0.25);
  border-color: #ef4444;
}

/* 分析档案 Drawer 样式 */
.plan-drawer-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.plan-card-overview {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--app-border);
  border-radius: 8px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.plan-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.plan-label {
  font-size: 12px;
  color: var(--app-text-muted);
}

.plan-val {
  font-size: 13px;
  font-weight: 600;
  color: var(--app-text-primary);
}

.highlight-val {
  color: var(--app-primary);
}

.plan-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.section-badge {
  font-size: 12px;
  font-weight: 700;
  color: var(--app-text-secondary);
}

.tag-wrap {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.plan-details-box {
  background: var(--app-bg-code);
  border: 1px solid var(--app-border-subtle);
  border-radius: 6px;
  padding: 10px 12px;
  font-size: 12.5px;
  line-height: 1.6;
}

.sub-item {
  color: var(--app-text-secondary);
}

.sub-item strong {
  color: var(--app-text-primary);
}

.plan-json-section {
  margin-top: 8px;
}

.json-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--app-text-muted);
}

.copy-json-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--app-border);
  border-radius: 4px;
  color: var(--app-text-secondary);
  font-size: 11px;
  cursor: pointer;
}

.copy-json-btn:hover {
  color: var(--app-primary);
  border-color: var(--app-primary);
}

.json-viewer {
  background: #090f1d;
  border: 1px solid var(--app-border);
  padding: 12px;
  border-radius: 6px;
  font-family: var(--app-font-mono);
  font-size: 11.5px;
  line-height: 1.55;
  color: #94a3b8;
  max-height: 280px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
