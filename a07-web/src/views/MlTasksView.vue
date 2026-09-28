<!-- AI-assisted -->
<!-- 建模工作台（F4）：六算法统一建模工作流，结构化建模参数配置、参数预设注入、代理运行与历史追溯。 -->
<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import type { MLResultPayload, ModelType } from '../types/agent'
import { describeHttpError, fetchCatalogTables, runMl } from '../api/http'
import { listColumns } from '../api/metadata'
import AppNav from '../components/AppNav.vue'
import MlResultCard from '../components/MlResultCard.vue'
import {
  Cpu,
  Timer,
  Tickets,
  Delete,
  View,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

/** 硬编码常用表（/api/catalog/tables 无已注册表或不可用时的降级选项，UI 标注"示例数据"，不伪造元数据） */
const FALLBACK_TABLES = ['process_output', 'quality_inspections', 'equipment_downtime'] as const

interface AlgorithmDef {
  value: ModelType
  label: string
  category: '回归分析' | '分类决策' | '无监督分析'
  desc: string
  needsTarget: boolean
  defaultParams: string
}

const ALGORITHMS: AlgorithmDef[] = [
  {
    value: 'linear_regression',
    label: '线性回归 (Linear Regression)',
    category: '回归分析',
    desc: '连续变量数值预测与线性趋势拟合',
    needsTarget: true,
    defaultParams: '{}',
  },
  {
    value: 'decision_tree',
    label: '决策树 (Decision Tree)',
    category: '分类决策',
    desc: '规则驱动分类与回归，可直观解释特征分支',
    needsTarget: true,
    defaultParams: '{"max_depth": 4}',
  },
  {
    value: 'random_forest',
    label: '随机森林 (Random Forest)',
    category: '回归分析',
    desc: '多树集成强泛化模型，输出高精度特征重要性',
    needsTarget: true,
    defaultParams: '{"n_estimators": 100, "max_depth": 5}',
  },
  {
    value: 'logistic_regression',
    label: '逻辑回归 (Logistic Regression)',
    category: '分类决策',
    desc: '对数几率二分类与概率预测',
    needsTarget: true,
    defaultParams: '{"max_iter": 200}',
  },
  {
    value: 'kmeans',
    label: 'KMeans 聚类 (Clustering)',
    category: '无监督分析',
    desc: '无监督样本自适应聚类划分与中心点收敛',
    needsTarget: false,
    defaultParams: '{"n_clusters": 3}',
  },
  {
    value: 'isolation_forest',
    label: '孤立森林 (Anomaly Detection)',
    category: '无监督分析',
    desc: '工业设备与生产指标异常样本自动隔离检测',
    needsTarget: false,
    defaultParams: '{"contamination": 0.05}',
  },
]

interface MlTaskHistoryEntry {
  taskId: string
  modelType: string
  taskType: string
  time: string
  payload: MLResultPayload
}

const HISTORY_KEY = 'a07_ml_tasks'

const PARAM_PRESETS = [
  { label: '随机森林 (100棵树/深5)', params: '{"n_estimators": 100, "max_depth": 5}' },
  { label: 'KMeans (k=3)', params: '{"n_clusters": 3}' },
  { label: '孤立森林 (异常率 5%)', params: '{"contamination": 0.05}' },
  { label: '空参数 ({})', params: '{}' },
] as const

const form = reactive({
  table: FALLBACK_TABLES[0] as string,
  features: [] as string[],
  target: '',
  modelType: 'random_forest' as ModelType,
  parametersText: '{"n_estimators": 100, "max_depth": 5}',
})

const tables = ref<string[]>([...FALLBACK_TABLES])
const featureOptions = ref<string[]>([])
const featureOptionsLoading = ref(false)
let featureOptionsSeq = 0

/** 元数据驱动：所选表的列清单作为特征/目标列唯一候选（禁止手输任意列名）。 */
async function loadFeatureOptions(): Promise<void> {
  const table = form.table
  if (!table || table.trim().length === 0) {
    featureOptions.value = []
    return
  }
  const seq = ++featureOptionsSeq
  featureOptionsLoading.value = true
  try {
    const page = await listColumns({ tableName: table, size: 100 })
    if (seq !== featureOptionsSeq) return
    featureOptions.value = Array.from(new Set(page.records.map((c) => c.columnName)))
    pruneSelectionsToOptions()
  } catch {
    // 元数据不可用：清空候选并放行提交（依赖后端 400 文案），不阻塞页面
    if (seq !== featureOptionsSeq) return
    featureOptions.value = []
  } finally {
    if (seq === featureOptionsSeq) featureOptionsLoading.value = false
  }
}

/** 换表/列清单更新后，剔除已选 features/target 中不在新列集合的项。 */
function pruneSelectionsToOptions(): void {
  const options = featureOptions.value
  if (options.length === 0) return
  const optionSet = new Set(options)
  form.features = form.features.filter((f) => optionSet.has(f))
  if (form.target && !optionSet.has(form.target)) {
    form.target = ''
  }
}

function describeAvailableColumns(): string {
  return featureOptions.value.length > 0
    ? `当前表 ${form.table} 可用列: ${featureOptions.value.join(', ')}`
    : `暂未获取到表 ${form.table} 的列元数据，请先在数据资源中心采集/刷新元数据`
}

/** 提交前校验：features/target 必须来自 featureOptions；options 为空时放行，依赖后端 400 文案。 */
function validateColumns(): boolean {
  const options = featureOptions.value
  if (options.length === 0) return true
  const optionSet = new Set(options)
  const invalidFeatures = form.features.filter((f) => !optionSet.has(f))
  if (invalidFeatures.length > 0) {
    submitError.value = `特征列不在当前表可用列中: ${invalidFeatures.join(', ')}。${describeAvailableColumns()}`
    return false
  }
  if (needsTarget.value) {
    const target = form.target.trim()
    if (target.length === 0 || !optionSet.has(target)) {
      submitError.value = target.length > 0
        ? `目标列不在当前表可用列中: ${target}。${describeAvailableColumns()}`
        : `请从当前表可用列中选择目标列。${describeAvailableColumns()}`
      return false
    }
  }
  return true
}

watch(
  () => form.table,
  () => {
    void loadFeatureOptions()
  },
)
const submitting = ref(false)
const submitError = ref('')
const paramError = ref('')
const result = ref<MLResultPayload | null>(null)
const history = ref<MlTaskHistoryEntry[]>(loadHistory())

const currentAlgorithm = computed(
  () => ALGORITHMS.find((a) => a.value === form.modelType) ?? ALGORITHMS[0],
)

const needsTarget = computed(() => currentAlgorithm.value.needsTarget)

const canSubmit = computed(
  () =>
    form.table.length > 0 &&
    form.features.length > 0 &&
    (!needsTarget.value || form.target.trim().length > 0) &&
    !submitting.value,
)

onMounted(async () => {
  void loadFeatureOptions()
  const remote = await fetchCatalogTables()
  if (remote && remote.length > 0) {
    tables.value = remote
    if (!remote.includes(form.table)) form.table = remote[0]
  }
})

function selectAlgorithm(algo: AlgorithmDef): void {
  form.modelType = algo.value
  form.parametersText = algo.defaultParams
}

function applyParamPreset(presetJson: string): void {
  form.parametersText = presetJson
  paramError.value = ''
}

function loadHistory(): MlTaskHistoryEntry[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as MlTaskHistoryEntry[]) : []
  } catch {
    return []
  }
}

function saveHistory(entry: MlTaskHistoryEntry): void {
  history.value = [entry, ...history.value].slice(0, 10)
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history.value))
  } catch {}
}

function showHistory(entry: MlTaskHistoryEntry): void {
  result.value = entry.payload
  submitError.value = ''
  ElMessage.info(`已载入历史任务: ${entry.taskId}`)
}

function clearHistory(): void {
  history.value = []
  try {
    localStorage.removeItem(HISTORY_KEY)
    ElMessage.success('建模历史已清空')
  } catch {}
}

async function submit(): Promise<void> {
  paramError.value = ''
  submitError.value = ''
  if (!validateColumns()) {
    ElMessage.error(submitError.value)
    return
  }
  let parameters: Record<string, unknown> = {}
  if (form.parametersText.trim().length > 0) {
    try {
      const parsed: unknown = JSON.parse(form.parametersText)
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        paramError.value = '参数必须是标准 JSON 对象，例如 {"n_clusters": 3}'
        return
      }
      parameters = parsed as Record<string, unknown>
    } catch {
      paramError.value = '参数不是合法 JSON 格式，请检查格式后重试'
      return
    }
  }
  submitting.value = true
  try {
    const payload = await runMl({
      model_type: form.modelType,
      features: form.features,
      target: needsTarget.value && form.target.trim().length > 0 ? form.target.trim() : null,
      parameters,
      data_ref: `SELECT * FROM ${form.table}`,
      question: `建模：${form.modelType} @ ${form.table}`,
    })
    result.value = payload
    saveHistory({
      taskId: payload.taskId,
      modelType: payload.modelType,
      taskType: payload.taskType,
      time: new Date().toLocaleString(),
      payload,
    })
    ElMessage.success('模型训练与评估完成')
  } catch (err) {
    submitError.value = describeHttpError(err)
    ElMessage.error(submitError.value)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="ml-workbench-page">
    <AppNav />

    <header class="page-header-banner">
      <div class="banner-inner">
        <div class="banner-left">
          <div class="banner-icon">
            <el-icon><Cpu /></el-icon>
          </div>
          <div>
            <h1 class="page-title">工业智能建模工作台</h1>
            <p class="page-sub">
              支持数值回归、分类决策、聚类分析与异常检测等多场景算法建模与评估
            </p>
          </div>
        </div>
      </div>
    </header>

    <main class="ml-main-container">
      <el-alert
        v-if="submitError"
        class="block-gap"
        type="error"
        show-icon
        :closable="false"
        :title="submitError"
      />

      <!-- 建模任务配置卡片 -->
      <div class="studio-card form-box">
        <div class="studio-head">
          <span class="head-title">新建工业算法建模任务</span>
          <span class="head-desc">配置特征字段与模型参数，生成模型诊断与评估结果</span>
        </div>

        <el-form label-position="top" @submit.prevent="submit" class="studio-form">
          <!-- 步骤一：数据源选择 -->
          <div class="form-section-title">
            <span class="section-bar"></span>
            <span>目标数据表与字段选择</span>
          </div>

          <div class="form-row-grid">
            <el-form-item label="训练数据表 (Target Table)" required>
              <el-select v-model="form.table" filterable placeholder="选择已注册数据表">
                <el-option v-for="table in tables" :key="table" :label="table" :value="table" />
              </el-select>
            </el-form-item>

            <el-form-item label="特征列 (Features)" required>
              <el-select
                v-model="form.features"
                multiple
                filterable
                :loading="featureOptionsLoading"
                :placeholder="featureOptions.length > 0 ? '从当前表可用列中选择特征字段' : '暂无可用列，请先采集元数据'"
              >
                <el-option v-for="col in featureOptions" :key="col" :label="col" :value="col" />
              </el-select>
            </el-form-item>

            <el-form-item
              :label="needsTarget ? '目标标签列 (Target Variable)' : '目标列 (无监督算法无需填)'"
              :required="needsTarget"
            >
              <el-select
                v-model="form.target"
                filterable
                clearable
                :disabled="!needsTarget"
                :loading="featureOptionsLoading"
                :placeholder="needsTarget
                  ? (featureOptions.length > 0 ? '从当前表可用列中选择目标列' : '暂无可用列，请先采集元数据')
                  : '— (当前算法无需目标列)'"
              >
                <el-option v-for="col in featureOptions" :key="col" :label="col" :value="col" />
              </el-select>
            </el-form-item>
          </div>

          <div v-if="featureOptions.length > 0" class="column-chips">
            <span class="chips-label">当前表可用列：</span>
            <span
              v-for="col in featureOptions"
              :key="col"
              class="column-chip"
              :class="{ 'is-selected': form.features.includes(col) || form.target === col }"
            >
              {{ col }}
            </span>
          </div>
          <div v-else class="column-chips-empty">
            {{ describeAvailableColumns() }}
          </div>

          <!-- 步骤二：算法选型 -->
          <div class="form-section-title">
            <span class="section-bar"></span>
            <span>选择算法模型 (Algorithm Engine)</span>
          </div>

          <div class="algorithm-selection-grid">
            <div
              v-for="algo in ALGORITHMS"
              :key="algo.value"
              class="algo-card"
              :class="{ 'is-selected': form.modelType === algo.value }"
              @click="selectAlgorithm(algo)"
            >
              <div class="algo-top">
                <span class="algo-name">{{ algo.label }}</span>
                <el-tag size="small" effect="plain" class="algo-cat-tag">
                  {{ algo.category }}
                </el-tag>
              </div>
              <p class="algo-desc">{{ algo.desc }}</p>
            </div>
          </div>

          <!-- 步骤三：超参数配置 -->
          <div class="form-section-title">
            <span class="section-bar"></span>
            <span>超参数配置 (Hyperparameters JSON)</span>
          </div>

          <div class="params-block">
            <div class="presets-row">
              <span class="preset-label">常用超参数预设:</span>
              <button
                v-for="p in PARAM_PRESETS"
                :key="p.label"
                type="button"
                class="param-chip"
                @click="applyParamPreset(p.params)"
              >
                {{ p.label }}
              </button>
            </div>

            <el-input
              v-model="form.parametersText"
              type="textarea"
              :rows="2"
              class="param-textarea"
              placeholder='例如 {"n_clusters": 3} 或 {"n_estimators": 100}'
            />
            <div v-if="paramError" class="param-error">{{ paramError }}</div>
          </div>

          <!-- 提交按钮与说明 -->
          <div class="submit-action-row">
            <button
              class="run-train-btn"
              type="button"
              :disabled="!canSubmit"
              @click="submit"
            >
              <el-icon :class="{ 'is-loading': submitting }">
                <Cpu v-if="!submitting" />
                <Timer v-else />
              </el-icon>
              <span>{{ submitting ? '模型训练中 · 正在计算指标与绘制诊断图...' : '开始算法建模与评估' }}</span>
            </button>
            <div class="ml-run-hint">真实建模含取数与沙箱训练，通常 15–90 秒（首次较慢），请勿关闭或刷新页面</div>
          </div>
        </el-form>
      </div>

      <!-- 建模结果卡片展示区 -->
      <div v-if="result" class="result-section">
        <MlResultCard :payload="result" />
      </div>

      <!-- 任务历史表格 -->
      <div v-if="history.length > 0" class="studio-card history-box">
        <div class="studio-head">
          <div class="head-left-group">
            <el-icon><Tickets /></el-icon>
            <span class="head-title">建模任务记录（本机暂存）</span>
          </div>
          <button class="clear-history-btn" @click="clearHistory">
            <el-icon><Delete /></el-icon>
            <span>清空记录</span>
          </button>
        </div>

        <el-table :data="history" size="small" border stripe class="custom-table">
          <el-table-column prop="taskId" label="任务 ID" min-width="180" show-overflow-tooltip>
            <template #default="scope">
              <span class="task-id-code">{{ scope.row.taskId }}</span>
            </template>
          </el-table-column>

          <el-table-column prop="modelType" label="模型算法" min-width="140" />

          <el-table-column prop="taskType" label="任务类别" width="110" align="center">
            <template #default="scope">
              <el-tag size="small" effect="plain">{{ scope.row.taskType }}</el-tag>
            </template>
          </el-table-column>

          <el-table-column prop="time" label="训练时间" min-width="150" />

          <el-table-column label="操作" width="100" align="center" fixed="right">
            <template #default="scope">
              <el-button
                size="small"
                text
                type="primary"
                @click="showHistory(scope.row as MlTaskHistoryEntry)"
              >
                <el-icon><View /></el-icon>
                <span>查看结果</span>
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </main>
  </div>
</template>

<style scoped>
.ml-workbench-page {
  min-height: 100vh;
  background: var(--app-bg-deep);
  display: flex;
  flex-direction: column;
}

.page-header-banner {
  background: var(--app-bg-surface);
  border-bottom: 1px solid var(--app-border);
  padding: 16px 32px;
}

.banner-inner {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.banner-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.banner-icon {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  background: rgba(168, 85, 247, 0.12);
  border: 1px solid rgba(168, 85, 247, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: #c084fc;
}

.page-title {
  margin: 0 0 4px;
  font-size: 20px;
  font-weight: 700;
  color: var(--app-text-primary);
}

.page-sub {
  margin: 0;
  font-size: 13px;
  color: var(--app-text-muted);
}

.banner-actions {
  display: flex;
  align-items: center;
}



.ml-main-container {
  max-width: 1200px;
  width: 100%;
  margin: 0 auto;
  padding: 20px 32px 40px;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.studio-card {
  background: var(--app-bg-card);
  border: 1px solid var(--app-border);
  border-radius: 12px;
  box-shadow: var(--app-shadow-card);
  overflow: hidden;
}

.studio-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  background: rgba(255, 255, 255, 0.02);
  border-bottom: 1px solid var(--app-border);
  flex-wrap: wrap;
  gap: 10px;
}

.head-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--app-text-primary);
}

.head-desc {
  font-size: 12px;
  color: var(--app-text-muted);
}

.studio-form {
  padding: 20px;
}

.form-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13.5px;
  font-weight: 700;
  color: var(--app-text-primary);
  margin: 18px 0 12px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--app-border-subtle);
}

.form-section-title:first-child {
  margin-top: 0;
}

.section-bar {
  width: 3px;
  height: 14px;
  border-radius: 2px;
  background: linear-gradient(180deg, var(--app-primary), var(--app-accent-emerald));
}

.form-row-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.algorithm-selection-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.algo-card {
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--app-border);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.algo-card:hover {
  background: rgba(56, 189, 248, 0.06);
  border-color: var(--app-border-hover);
  transform: translateY(-2px);
}

.algo-card.is-selected {
  background: rgba(56, 189, 248, 0.12);
  border-color: var(--app-primary);
  box-shadow: 0 0 14px -3px var(--app-primary-glow);
}

.algo-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.algo-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--app-text-primary);
}

.algo-cat-tag {
  font-size: 10px;
  height: 20px;
  line-height: 18px;
}

.algo-desc {
  margin: 0;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--app-text-muted);
}

.params-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 20px;
}

.presets-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.preset-label {
  font-size: 12px;
  color: var(--app-text-muted);
}

.param-chip {
  padding: 3px 8px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--app-border-subtle);
  border-radius: 4px;
  color: var(--app-text-secondary);
  font-size: 11px;
  font-family: var(--app-font-mono);
  cursor: pointer;
  transition: all 0.2s ease;
}

.param-chip:hover {
  background: rgba(56, 189, 248, 0.1);
  color: var(--app-primary);
  border-color: var(--app-primary);
}

.param-error {
  color: var(--app-accent-rose);
  font-size: 12px;
}

.column-chips {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin: -4px 0 12px;
}

.chips-label {
  font-size: 12px;
  color: var(--app-text-muted);
}

.column-chip {
  padding: 2px 8px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--app-border-subtle);
  border-radius: 4px;
  color: var(--app-text-secondary);
  font-size: 11px;
  font-family: var(--app-font-mono);
}

.column-chip.is-selected {
  background: rgba(56, 189, 248, 0.12);
  border-color: var(--app-primary);
  color: var(--app-primary);
}

.column-chips-empty {
  margin: -4px 0 12px;
  font-size: 12px;
  color: var(--app-text-muted);
}

.submit-action-row {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  padding-top: 8px;
}

.ml-run-hint {
  font-size: 12px;
  color: var(--app-text-muted);
}

.run-train-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 44px;
  padding: 0 24px;
  background: var(--app-gradient-primary);
  border: none;
  border-radius: 8px;
  color: #ffffff;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 4px 16px rgba(14, 165, 233, 0.4);
  transition: all 0.25s ease;
}

.run-train-btn:hover:not(:disabled) {
  opacity: 0.95;
  box-shadow: 0 6px 20px rgba(14, 165, 233, 0.55);
}

.run-train-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  box-shadow: none;
}



.result-section {
  margin-top: 4px;
}

.history-box {
  padding: 0;
}

.head-left-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.clear-history-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.25);
  border-radius: 6px;
  color: #f87171;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.clear-history-btn:hover {
  background: rgba(239, 68, 68, 0.18);
}

.task-id-code {
  font-family: var(--app-font-mono);
  font-size: 11.5px;
  color: var(--app-primary);
}

.block-gap {
  margin-bottom: 12px;
}

@media (max-width: 900px) {
  .form-row-grid,
  .algorithm-selection-grid {
    grid-template-columns: 1fr;
  }
}
</style>

