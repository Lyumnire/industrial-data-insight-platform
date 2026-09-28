<!-- AI-assisted -->
<!-- 报告卡片：多步决策分析综合报告卡，安全渲染 Markdown，支持复制与文件下载。 -->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { renderSimpleMarkdown } from '../utils/markup'
import { TOPIC_LABELS } from '../utils/mlcharts'
import {
  Document,
  Download,
  DocumentCopy,
  Warning,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const props = defineProps<{
  reportId: string
  markdown: string
  topic?: string
  warnings?: string[]
}>()

const copied = ref(false)

const renderedHtml = computed(() => renderSimpleMarkdown(props.markdown))

const topicLabel = computed(() => {
  const key = props.topic as keyof typeof TOPIC_LABELS | undefined
  return key && TOPIC_LABELS[key] ? TOPIC_LABELS[key] : props.topic
})

const fileName = computed(() =>
  props.reportId ? `${props.reportId}.md` : `report-${Date.now()}.md`,
)

function downloadMarkdown(): void {
  const blob = new Blob([props.markdown], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName.value
  anchor.click()
  URL.revokeObjectURL(url)
  ElMessage.success('报告 Markdown 文件已下载')
}

async function copyReport(): Promise<void> {
  try {
    await navigator.clipboard.writeText(props.markdown)
    copied.value = true
    ElMessage.success('报告内容已复制')
    setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch {
    ElMessage.warning('复制失败')
  }
}
</script>

<template>
  <div class="report-container">
    <div class="report-header">
      <div class="header-left">
        <div class="header-icon">
          <el-icon><Document /></el-icon>
        </div>
        <div class="title-group">
          <span class="report-title">业务综合分析报告</span>
          <span v-if="topicLabel" class="topic-badge">{{ topicLabel }}</span>
        </div>
      </div>

      <div class="header-right">
        <span class="report-id-pill">ID: {{ reportId || 'REPORT' }}</span>
        <button class="tool-btn" @click="copyReport">
          <el-icon><DocumentCopy /></el-icon>
          <span>{{ copied ? '已复制' : '复制' }}</span>
        </button>
        <button class="tool-btn primary-tool" @click="downloadMarkdown">
          <el-icon><Download /></el-icon>
          <span>下载 .md</span>
        </button>
      </div>
    </div>

    <div v-if="warnings && warnings.length > 0" class="warnings-area">
      <div v-for="w in warnings" :key="w" class="warn-pill">
        <el-icon><Warning /></el-icon>
        <span>{{ w }}</span>
      </div>
    </div>

    <div class="report-content-frame">
      <div class="report-sheet">
        <div class="md-text report-body" v-html="renderedHtml"></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.report-container {
  margin-bottom: 14px;
  background: var(--app-bg-card);
  border: 1px solid var(--app-border);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.35);
}

.report-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: linear-gradient(90deg, rgba(56, 189, 248, 0.08) 0%, rgba(99, 102, 241, 0.04) 100%);
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
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: rgba(56, 189, 248, 0.15);
  color: #38bdf8;
  font-size: 16px;
}

.title-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.report-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--app-text-primary);
}

.topic-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  background: rgba(56, 189, 248, 0.12);
  border: 1px solid rgba(56, 189, 248, 0.25);
  color: #38bdf8;
  border-radius: 9999px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.report-id-pill {
  font-family: var(--app-font-mono);
  font-size: 11px;
  color: var(--app-text-muted);
  background: rgba(255, 255, 255, 0.04);
  padding: 3px 8px;
  border-radius: 4px;
  border: 1px solid var(--app-border-subtle);
}

.tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--app-border);
  color: var(--app-text-secondary);
  font-size: 11.5px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.tool-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: var(--app-text-primary);
}

.primary-tool {
  background: rgba(56, 189, 248, 0.12);
  border-color: rgba(56, 189, 248, 0.3);
  color: var(--app-primary);
  font-weight: 600;
}

.primary-tool:hover {
  background: rgba(56, 189, 248, 0.22);
}

.warnings-area {
  padding: 8px 16px;
  background: rgba(245, 158, 11, 0.06);
  border-bottom: 1px solid rgba(245, 158, 11, 0.15);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.warn-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #f59e0b;
}

.report-content-frame {
  padding: 16px 20px;
}

.report-sheet {
  background: rgba(0, 0, 0, 0.15);
  border: 1px solid var(--app-border-subtle);
  border-radius: 8px;
  padding: 18px 24px;
  max-height: 540px;
  overflow-y: auto;
}

html:not(.dark) .report-sheet {
  background: #ffffff;
}

.report-body :deep(h1),
.report-body :deep(h2),
.report-body :deep(h3) {
  color: var(--app-text-primary);
  border-bottom: 1px solid var(--app-border-subtle);
  padding-bottom: 6px;
  margin-top: 14px;
}

.report-body :deep(h1) { font-size: 18px; }
.report-body :deep(h2) { font-size: 16px; }
.report-body :deep(h3) { font-size: 14.5px; }
</style>
