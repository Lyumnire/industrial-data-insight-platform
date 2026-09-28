<!-- AI-assisted -->
<!-- 建模结果卡片：多算法工业建模评估仪表板，指标大卡、特征重要性、诊断图与预测样本呈现。 -->
<script setup lang="ts">
import { computed } from 'vue'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'
import type { MLResultPayload } from '../types/agent'
import type { ChartCardData } from '../stores/chat'
import ChartCard from './ChartCard.vue'
import {
  MODEL_TYPE_LABELS,
  TASK_TYPE_LABELS,
  buildMlPlotOption,
  formatMetricValue,
  metricLabel,
} from '../utils/mlcharts'
import {
  Cpu,
  FolderOpened,
  InfoFilled,
  TrendCharts,
  Tickets,
  Grid,
} from '@element-plus/icons-vue'

const props = defineProps<{
  payload: MLResultPayload
}>()

const importanceItems = computed(() =>
  props.payload.featureImportance && props.payload.featureImportance.length > 0
    ? props.payload.featureImportance
    : props.payload.feature_importance || [],
)

const sampleRows = computed(() =>
  props.payload.predictionsSample && props.payload.predictionsSample.length > 0
    ? props.payload.predictionsSample
    : props.payload.predictions_sample || [],
)

const taskLabel = computed(() => props.payload.taskId || props.payload.task_id)
const pathLabel = computed(() => props.payload.modelPath ?? props.payload.model_path)

const metricEntries = computed(() => Object.entries(props.payload.metrics || {}))

const modelTypeLabel = computed(() => {
  const key = props.payload.modelType as keyof typeof MODEL_TYPE_LABELS
  return MODEL_TYPE_LABELS[key] ?? props.payload.modelType
})

const taskTypeLabel = computed(() => {
  const key = props.payload.taskType as keyof typeof TASK_TYPE_LABELS
  return TASK_TYPE_LABELS[key] ?? props.payload.taskType
})

const chartCards = computed<ChartCardData[]>(() =>
  (props.payload.plots || [])
    .map((plot, index): ChartCardData | null => {
      const option: EChartsOption | null = buildMlPlotOption(plot)
      return option === null ? null : { id: index, chartType: plot.type, option }
    })
    .filter((card): card is ChartCardData => card !== null),
)

const fallbackPlots = computed(() =>
  (props.payload.plots || []).filter((plot) => buildMlPlotOption(plot) === null),
)

const featureImportanceChart = computed<ChartCardData | null>(() => {
  const items = importanceItems.value
  if (!items || items.length === 0) return null
  const sorted = [...items].sort((a, b) => a.score - b.score)
  return {
    id: 999,
    chartType: 'bar',
    option: {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
      },
      grid: { left: 140, right: 30, top: 20, bottom: 30 },
      xAxis: {
        type: 'value',
        name: '重要性得分',
        splitLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.15)' } },
      },
      yAxis: {
        type: 'category',
        data: sorted.map((item) => item.name),
        axisLabel: { color: '#94a3b8' },
      },
      series: [
        {
          type: 'bar',
          name: '特征重要性',
          data: sorted.map((item) => item.score),
          itemStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
              { offset: 0, color: '#38bdf8' },
              { offset: 1, color: '#818cf8' },
            ]),
            borderRadius: [0, 4, 4, 0],
          },
        },
      ],
    },
  }
})

const sampleColumns = computed(() => {
  const first = sampleRows.value[0]
  return first ? Object.keys(first) : []
})

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
</script>

<template>
  <div class="ml-result-card">
    <div class="card-header">
      <div class="header-left">
        <div class="header-icon">
          <el-icon><Cpu /></el-icon>
        </div>
        <div class="title-wrap">
          <span class="card-title">机器学习建模评估 · {{ modelTypeLabel }}</span>
          <span class="task-badge">{{ taskTypeLabel }}</span>
        </div>
      </div>

      <div class="header-right">
        <span class="id-pill">任务: {{ taskLabel }}</span>
        <span v-if="pathLabel" class="path-pill">
          <el-icon><FolderOpened /></el-icon>
          {{ pathLabel }}
        </span>
      </div>
    </div>

    <div v-if="payload.warnings && payload.warnings.length > 0" class="warn-section">
      <el-alert
        v-for="warning in payload.warnings"
        :key="warning"
        type="warning"
        show-icon
        :closable="false"
        :title="warning"
        class="ml-warn-alert"
      />
    </div>

    <!-- 核心指标 KPI 栅格 -->
    <div class="section-title">
      <el-icon><Tickets /></el-icon>
      <span>模型综合评估指标</span>
    </div>
    <div class="metric-kpi-grid">
      <div
        v-for="[key, value] in metricEntries"
        :key="key"
        class="metric-box"
      >
        <span class="metric-name">{{ metricLabel(key) }}</span>
        <span class="metric-val">{{ formatMetricValue(key, value) }}</span>
      </div>
    </div>

    <!-- 特征重要性 -->
    <template v-if="featureImportanceChart">
      <div class="section-title">
        <el-icon><TrendCharts /></el-icon>
        <span>特征重要性分析 (Feature Importance)</span>
      </div>
      <ChartCard :card="featureImportanceChart" />
    </template>

    <!-- 诊断图 -->
    <template v-if="chartCards.length > 0">
      <div class="section-title">
        <el-icon><TrendCharts /></el-icon>
        <span>模型诊断与收敛曲线</span>
      </div>
      <ChartCard v-for="card in chartCards" :key="card.id" :card="card" />
    </template>

    <!-- 原始图数据降级 -->
    <template v-for="(plot, index) in fallbackPlots" :key="'fb' + index">
      <div class="section-title">诊断图数据（{{ plot.type }}）</div>
      <pre class="raw-json">{{ plot.data }}</pre>
    </template>

    <!-- 预测样本表格 -->
    <template v-if="sampleRows.length > 0">
      <div class="section-title">
        <el-icon><Grid /></el-icon>
        <span>预测推断样本明细（{{ sampleRows.length }} 行）</span>
      </div>
      <div class="sample-table-wrap">
        <el-table :data="sampleRows" size="small" border stripe max-height="300">
          <el-table-column
            v-for="column in sampleColumns"
            :key="column"
            :prop="column"
            :label="column"
            min-width="120"
            show-overflow-tooltip
          >
            <template #default="scope">
              <span class="sample-cell">{{ formatCell(scope.row[column]) }}</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </template>

    <!-- 模型解释 -->
    <template v-if="payload.explanation">
      <div class="section-title">
        <el-icon><InfoFilled /></el-icon>
        <span>模型业务解释与决策洞察</span>
      </div>
      <div class="explanation-box">
        <p>{{ payload.explanation }}</p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.ml-result-card {
  margin-bottom: 14px;
  background: var(--app-bg-card);
  border: 1px solid var(--app-border);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.3);
  padding: 16px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--app-border);
  gap: 12px;
  flex-wrap: wrap;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: rgba(168, 85, 247, 0.15);
  color: #a855f7;
  font-size: 18px;
}

.title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--app-text-primary);
}

.task-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  background: rgba(168, 85, 247, 0.12);
  border: 1px solid rgba(168, 85, 247, 0.28);
  color: #c084fc;
  border-radius: 9999px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.id-pill {
  font-family: var(--app-font-mono);
  font-size: 11px;
  color: var(--app-text-muted);
  background: rgba(255, 255, 255, 0.04);
  padding: 3px 8px;
  border-radius: 4px;
  border: 1px solid var(--app-border-subtle);
}

.path-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: var(--app-font-mono);
  font-size: 11px;
  color: #38bdf8;
  background: rgba(56, 189, 248, 0.08);
  padding: 3px 8px;
  border-radius: 4px;
  border: 1px solid rgba(56, 189, 248, 0.2);
}

.warn-section {
  margin: 12px 0;
}

.ml-warn-alert {
  margin-bottom: 8px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--app-text-primary);
  margin: 16px 0 10px;
}

.metric-kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.metric-box {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--app-border);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.metric-name {
  font-size: 11.5px;
  color: var(--app-text-muted);
}

.metric-val {
  font-size: 18px;
  font-weight: 700;
  font-family: var(--app-font-mono);
  color: #38bdf8;
}

.sample-table-wrap {
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--app-border);
}

.sample-cell {
  font-family: var(--app-font-mono);
  font-size: 12px;
}

.explanation-box {
  background: rgba(56, 189, 248, 0.06);
  border-left: 3px solid #38bdf8;
  padding: 12px 16px;
  border-radius: 0 8px 8px 0;
  color: var(--app-text-secondary);
  font-size: 13.5px;
  line-height: 1.65;
}

.explanation-box p {
  margin: 0;
}

.raw-json {
  background: #090f1d;
  padding: 10px;
  border-radius: 6px;
  font-family: var(--app-font-mono);
  font-size: 11.5px;
  overflow-x: auto;
  color: #94a3b8;
}
</style>
