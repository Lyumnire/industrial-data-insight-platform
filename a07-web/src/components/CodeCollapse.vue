<!-- AI-assisted -->
<!-- SQL 代码卡片：呈现 SQL 阶段链（生成/安全校验/执行），支持语法高亮风格、复制与执行度量。 -->
<script setup lang="ts">
import { computed, ref } from 'vue'
import type { SqlRun } from '../stores/chat'
import { ElMessage } from 'element-plus'
import {
  DocumentCopy,
  Check,
  Warning,
  CircleCheck,
  Refresh,
  Monitor,
} from '@element-plus/icons-vue'

const props = defineProps<{
  run: SqlRun
}>()

const isExpanded = ref(true)
const copied = ref(false)

const stageInfo = computed(() => {
  switch (props.run.stage) {
    case 'generated':
      return { label: '已生成 · 待校验', type: 'info', icon: Refresh }
    case 'validated':
      return { label: '安全合规校验通过', type: 'success', icon: CircleCheck }
    case 'invalid':
      return { label: '未通过安全校验', type: 'danger', icon: Warning }
    case 'executing':
      return { label: '正在执行查询...', type: 'warning', icon: Refresh }
    case 'completed':
      return { label: '执行完成', type: 'success', icon: Check }
  }
})

async function copySql(): Promise<void> {
  try {
    await navigator.clipboard.writeText(props.run.sql)
    copied.value = true
    ElMessage.success('SQL 已复制到剪贴板')
    setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch {
    ElMessage.warning('复制失败，请手动选择复制')
  }
}
</script>

<template>
  <div class="sql-card">
    <div class="sql-header">
      <div class="header-main" @click="isExpanded = !isExpanded">
        <div class="header-icon">
          <el-icon><Monitor /></el-icon>
        </div>
        <div class="title-group">
          <span class="card-title">SQL 执行脚本</span>
          <span class="sandbox-tag">受控只读</span>
        </div>

        <el-tag
          :type="stageInfo.type as any"
          size="small"
          effect="dark"
          class="stage-tag"
        >
          <el-icon class="stage-icon"><component :is="stageInfo.icon" /></el-icon>
          {{ stageInfo.label }}
        </el-tag>

        <span v-if="run.attempt > 0" class="repair-pill">
          执行重试 (第 {{ run.attempt + 1 }} 次)
        </span>

        <span v-if="run.stage === 'completed'" class="exec-metrics">
          {{ run.rowCount ?? 0 }} 行 · {{ run.elapsedMs ?? 0 }}ms
        </span>
      </div>

      <div class="header-actions">
        <el-tooltip content="复制完整 SQL" placement="top">
          <button class="action-btn" @click="copySql">
            <el-icon><DocumentCopy /></el-icon>
            <span>{{ copied ? '已复制' : '复制' }}</span>
          </button>
        </el-tooltip>
      </div>
    </div>

    <div v-show="isExpanded" class="sql-body">
      <div class="code-container">
        <div class="code-line-glow"></div>
        <pre class="sql-code"><code>{{ run.sql }}</code></pre>
      </div>

      <div v-if="run.message" class="validation-bar" :class="{ 'is-invalid': run.stage === 'invalid' }">
        <el-icon class="val-icon">
          <CircleCheck v-if="run.stage !== 'invalid'" />
          <Warning v-else />
        </el-icon>
        <span class="val-text">{{ run.message }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sql-card {
  margin-bottom: 14px;
  background: #090f1d;
  border: 1px solid var(--app-border);
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 4px 16px -2px rgba(0, 0, 0, 0.35);
}

html:not(.dark) .sql-card {
  background: #0f172a;
}

.sql-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.03);
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
}

.header-main {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  cursor: pointer;
  user-select: none;
  flex-wrap: wrap;
}

.header-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 6px;
  background: rgba(56, 189, 248, 0.12);
  color: #38bdf8;
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
  color: #f8fafc;
}

.sandbox-tag {
  font-size: 10.5px;
  padding: 2px 7px;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.25);
  color: #10b981;
  border-radius: 4px;
}

.stage-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  border-radius: 4px;
}

.stage-icon {
  font-size: 12px;
}

.repair-pill {
  font-size: 11px;
  padding: 2px 8px;
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.3);
  color: #f59e0b;
  border-radius: 4px;
}

.exec-metrics {
  font-size: 11.5px;
  font-family: var(--app-font-mono);
  color: #94a3b8;
  background: rgba(255, 255, 255, 0.04);
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--app-border);
  color: #cbd5e1;
  font-size: 11.5px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.action-btn:hover {
  background: rgba(56, 189, 248, 0.15);
  border-color: #38bdf8;
  color: #ffffff;
}

.sql-body {
  position: relative;
}

.code-container {
  position: relative;
  padding: 14px 18px;
  background: #050914;
}

.sql-code {
  margin: 0;
  padding: 0;
  font-family: var(--app-font-mono);
  font-size: 13px;
  line-height: 1.65;
  color: #e2e8f0;
  white-space: pre-wrap;
  word-break: break-all;
}

.validation-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: rgba(16, 185, 129, 0.08);
  border-top: 1px solid rgba(16, 185, 129, 0.2);
  color: #34d399;
  font-size: 12px;
}

.validation-bar.is-invalid {
  background: rgba(239, 68, 68, 0.08);
  border-top-color: rgba(239, 68, 68, 0.2);
  color: #f87171;
}

.val-icon {
  font-size: 14px;
}
</style>
