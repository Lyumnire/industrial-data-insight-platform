<!-- AI-assisted -->
<!-- 图表卡片：基于 Apache ECharts 渲染后端的图表载荷，包含暗色/亮色适配与自适应 ResizeObserver。 -->
<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'
import type { ChartCardData } from '../stores/chat'
import {
  TrendCharts,
  Picture,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const props = defineProps<{
  card: ChartCardData
}>()

const hostRef = ref<HTMLDivElement | null>(null)
let instance: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null

const chartTypeMap: Record<string, string> = {
  bar: '柱状图 (Bar Chart)',
  line: '折线趋势图 (Line Trend)',
  pie: '构成占比图 (Pie Distribution)',
  scatter: '相关性散点图 (Scatter Correlation)',
  table: '数据表 (Table)',
}

/**
 * BUG-018 保护：setOption 前强制合并 grid 留白与 legend 布局，避免标题压图例/柱与类目错位。
 * 注入现代工业科技配色与磨砂 Tooltip。
 */
function mergeChartOption(raw: unknown): EChartsOption {
  const option: Record<string, unknown> =
    typeof raw === 'object' && raw !== null ? { ...(raw as Record<string, unknown>) } : {}
  const title = option.title
  const legendRaw = option.legend
  const legendObj =
    Array.isArray(legendRaw) && legendRaw.length > 0
      ? ({ ...(legendRaw[0] as Record<string, unknown>) } as Record<string, unknown>)
      : typeof legendRaw === 'object' && legendRaw !== null
        ? { ...(legendRaw as Record<string, unknown>) }
        : null
  const hasTitle = Boolean(title)
  const hasLegend = legendObj !== null

  const gridRaw =
    typeof option.grid === 'object' && option.grid !== null && !Array.isArray(option.grid)
      ? { ...(option.grid as Record<string, unknown>) }
      : {}
  const num = (v: unknown, fallback: number): number => {
    return typeof v === 'number' && Number.isFinite(v) ? v : fallback
  }

  const topNeed = hasTitle || hasLegend ? 72 : 28
  const bottomNeed = 52

  // 现代科技配色环
  const techColorPalette = [
    '#38bdf8',
    '#818cf8',
    '#34d399',
    '#fbbf24',
    '#f43f5e',
    '#c084fc',
    '#2dd4bf',
    '#f97316',
  ]

  option.color = option.color ?? techColorPalette

  option.grid = {
    ...gridRaw,
    top: Math.max(num(gridRaw.top, 0), topNeed),
    bottom: Math.max(num(gridRaw.bottom, 0), bottomNeed),
    left: Math.max(num(gridRaw.left, 0), 48),
    right: Math.max(num(gridRaw.right, 0), 24),
    containLabel: true,
  }

  // 磨砂玻璃 Tooltip
  const tooltipRaw =
    typeof option.tooltip === 'object' && option.tooltip !== null
      ? (option.tooltip as Record<string, unknown>)
      : {}
  option.tooltip = {
    ...tooltipRaw,
    backgroundColor: 'rgba(15, 23, 42, 0.88)',
    borderColor: 'rgba(56, 189, 248, 0.35)',
    borderWidth: 1,
    padding: [8, 12],
    textStyle: {
      color: '#f8fafc',
      fontSize: 12.5,
    },
    shadowBlur: 16,
    shadowColor: 'rgba(0, 0, 0, 0.4)',
  }

  if (legendObj) {
    option.legend = {
      ...legendObj,
      type: 'scroll',
      top: hasTitle ? 32 : 10,
      left: 'center',
      textStyle: {
        color: '#94a3b8',
      },
    }
  }

  return option as EChartsOption
}

function handleResize(): void {
  instance?.resize()
}

function exportImage(): void {
  if (!instance) return
  const dataUrl = instance.getDataURL({
    type: 'png',
    pixelRatio: 2,
    backgroundColor: '#0f172a',
  })
  const a = document.createElement('a')
  a.href = dataUrl
  a.download = `chart_${props.card.chartType || 'visualization'}_${Date.now()}.png`
  a.click()
  ElMessage.success('图表图片已下载')
}

onMounted(() => {
  if (!hostRef.value) return
  instance = echarts.init(hostRef.value)
  instance.setOption(mergeChartOption(props.card.option))

  window.addEventListener('resize', handleResize)

  if (typeof ResizeObserver !== 'undefined' && hostRef.value) {
    resizeObserver = new ResizeObserver(() => {
      handleResize()
    })
    resizeObserver.observe(hostRef.value)
  }
})

watch(
  () => props.card.option,
  (option) => {
    instance?.setOption(mergeChartOption(option), true)
  },
)

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  resizeObserver?.disconnect()
  resizeObserver = null
  instance?.dispose()
  instance = null
})
</script>

<template>
  <div class="chart-card">
    <div class="chart-header">
      <div class="header-left">
        <div class="header-icon">
          <el-icon><TrendCharts /></el-icon>
        </div>
        <div class="title-group">
          <span class="card-title">数据可视化洞察</span>
          <span class="type-pill">
            {{ chartTypeMap[card.chartType] ?? (card.chartType || '自适应图表') }}
          </span>
        </div>
      </div>

      <div class="header-actions">
        <el-tooltip content="保存图表为高清图片" placement="top">
          <button class="tool-btn" @click="exportImage">
            <el-icon><Picture /></el-icon>
            <span>导出图片</span>
          </button>
        </el-tooltip>
      </div>
    </div>

    <div class="chart-canvas-wrap">
      <div ref="hostRef" class="chart-host"></div>
    </div>
  </div>
</template>

<style scoped>
.chart-card {
  margin-bottom: 14px;
  background: var(--app-bg-card);
  border: 1px solid var(--app-border);
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 4px 16px -2px rgba(0, 0, 0, 0.25);
}

.chart-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.02);
  border-bottom: 1px solid var(--app-border);
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
  width: 26px;
  height: 26px;
  border-radius: 6px;
  background: rgba(129, 140, 248, 0.12);
  color: #818cf8;
  font-size: 15px;
}

.title-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-title {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--app-text-primary);
}

.type-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  background: rgba(129, 140, 248, 0.1);
  border: 1px solid rgba(129, 140, 248, 0.25);
  color: #a5b4fc;
  border-radius: 9999px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--app-border);
  color: var(--app-text-secondary);
  font-size: 11.5px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.tool-btn:hover {
  background: rgba(129, 140, 248, 0.15);
  border-color: #818cf8;
  color: #ffffff;
}

.chart-canvas-wrap {
  padding: 10px 14px 14px;
}

.chart-host {
  width: 100%;
  height: 330px;
}
</style>
