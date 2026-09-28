<!-- AI-assisted -->
<!-- 结果表格卡片：高质感企业级数据表格，支持字段自适应、数值对齐、执行信息与前端 CSV 导出。 -->
<script setup lang="ts">
import { computed } from 'vue'
import type { TableCard } from '../stores/chat'
import {
  Grid,
  Download,
  WarningFilled,
  Timer,
  Coin,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const MAX_ROWS = 100

const props = defineProps<{
  card: TableCard
}>()

const displayRows = computed(() => props.card.rows.slice(0, MAX_ROWS))

function formatCell(value: string | number | boolean | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return String(value)
}

function isNumericValue(val: unknown): boolean {
  if (typeof val === 'number') return true
  if (typeof val === 'string' && val.trim() !== '' && !isNaN(Number(val))) return true
  return false
}

function exportCsv(): void {
  if (props.card.rows.length === 0) {
    ElMessage.info('暂无数据可导出')
    return
  }
  const headers = props.card.columns
  const rows = props.card.rows.map((row) =>
    headers
      .map((col) => {
        const val = row[col]
        const str = val === null || val === undefined ? '' : String(val)
        return `"${str.replace(/"/g, '""')}"`
      })
      .join(','),
  )
  const csvContent = '\uFEFF' + [headers.join(','), ...rows].join('\r\n')
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `query_result_${Date.now()}.csv`
  a.click()
  URL.revokeObjectURL(a.href)
  ElMessage.success('已导出 CSV 文件')
}
</script>

<template>
  <div class="result-table-card">
    <div class="table-header">
      <div class="header-left">
        <div class="header-icon">
          <el-icon><Grid /></el-icon>
        </div>
        <div class="title-wrap">
          <span class="card-title">查询结果集</span>
          <span class="row-badge">
            共 {{ card.total }} 行<template v-if="card.total > displayRows.length">（展示前 {{ displayRows.length }} 行）</template>
          </span>
        </div>
      </div>

      <div class="header-right">
        <span class="meta-pill">
          <el-icon><Coin /></el-icon>
          {{ card.executionInfo.dataSource }}
        </span>
        <span class="meta-pill">
          <el-icon><Timer /></el-icon>
          {{ card.executionInfo.durationMs }}ms
        </span>
        <button class="export-btn" @click="exportCsv">
          <el-icon><Download /></el-icon>
          <span>导出 CSV</span>
        </button>
      </div>
    </div>

    <div class="table-container">
      <el-table
        :data="displayRows"
        size="small"
        border
        stripe
        max-height="380"
        class="custom-data-table"
      >
        <el-table-column
          type="index"
          label="#"
          width="50"
          align="center"
        />
        <el-table-column
          v-for="column in card.columns"
          :key="column"
          :prop="column"
          :label="column"
          min-width="130"
          show-overflow-tooltip
        >
          <template #default="scope">
            <span
              :class="{
                'numeric-cell': isNumericValue(scope.row[column]),
                'null-cell': scope.row[column] === null || scope.row[column] === undefined,
              }"
            >
              {{ formatCell(scope.row[column]) }}
            </span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div v-if="card.executionInfo.truncated" class="truncation-alert">
      <el-icon><WarningFilled /></el-icon>
      <span>已达系统返回上限（强制 LIMIT 防卫生效），可进一步增加聚合或时间范围等过滤条件。</span>
    </div>
  </div>
</template>

<style scoped>
.result-table-card {
  margin-bottom: 14px;
  background: var(--app-bg-card);
  border: 1px solid var(--app-border);
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 4px 16px -2px rgba(0, 0, 0, 0.25);
}

.table-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.02);
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
  width: 26px;
  height: 26px;
  border-radius: 6px;
  background: rgba(16, 185, 129, 0.12);
  color: #10b981;
  font-size: 15px;
}

.title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-title {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--app-text-primary);
}

.row-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.25);
  color: #10b981;
  border-radius: 9999px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.meta-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--app-text-muted);
  background: rgba(255, 255, 255, 0.04);
  padding: 3px 8px;
  border-radius: 4px;
  border: 1px solid var(--app-border-subtle);
  font-family: var(--app-font-mono);
}

.export-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: rgba(56, 189, 248, 0.08);
  border: 1px solid rgba(56, 189, 248, 0.3);
  color: var(--app-primary);
  font-size: 11.5px;
  font-weight: 500;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.export-btn:hover {
  background: rgba(56, 189, 248, 0.18);
  border-color: var(--app-primary);
}

.table-container {
  padding: 2px;
}

.numeric-cell {
  font-family: var(--app-font-mono);
  font-weight: 500;
}

.null-cell {
  color: var(--app-text-muted);
  font-style: italic;
}

.truncation-alert {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  background: rgba(245, 158, 11, 0.08);
  border-top: 1px solid rgba(245, 158, 11, 0.2);
  color: #f59e0b;
  font-size: 12px;
}
</style>
