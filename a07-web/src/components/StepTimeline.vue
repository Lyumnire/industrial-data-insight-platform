<!-- AI-assisted -->
<!-- 步骤时间线：高质感 Agent 推理与执行管线（Step Stepper），展示多步自主推理轨迹。 -->
<script setup lang="ts">
import { ref } from 'vue'
import type { StepItem } from '../stores/chat'
import {
  CircleCheckFilled,
  Loading,
  CaretBottom,
  CaretRight,
  Connection,
} from '@element-plus/icons-vue'

const props = defineProps<{
  steps: StepItem[]
}>()

const isExpanded = ref(true)

function toggleExpand(): void {
  isExpanded.value = !isExpanded.value
}
</script>

<template>
  <div class="pipeline-container">
    <div class="pipeline-header" @click="toggleExpand">
      <div class="header-left">
        <div class="pipeline-badge">
          <el-icon><Connection /></el-icon>
        </div>
        <span class="pipeline-title">分析执行流程</span>
        <span class="step-counter">
          {{ steps.filter((s) => s.status === 'finished').length }}/{{ steps.length }} 步骤
        </span>
      </div>
      <div class="header-right">
        <span class="expand-hint">{{ isExpanded ? '收起明细' : '展开明细' }}</span>
        <el-icon class="expand-icon"><CaretBottom v-if="isExpanded" /><CaretRight v-else /></el-icon>
      </div>
    </div>

    <transition name="pipeline-collapse">
      <div v-show="isExpanded" class="steps-wrapper">
        <div
          v-for="(step, index) in steps"
          :key="step.stepId"
          class="step-node"
          :class="[`is-${step.status}`]"
        >
          <!-- 左侧节点与连线 -->
          <div class="node-rail">
            <div class="node-indicator">
              <el-icon v-if="step.status === 'finished'" class="icon-finished">
                <CircleCheckFilled />
              </el-icon>
              <el-icon v-else class="icon-running is-loading">
                <Loading />
              </el-icon>
            </div>
            <div v-if="index < steps.length - 1" class="rail-line"></div>
          </div>

          <!-- 右侧内容 -->
          <div class="node-content">
            <div class="node-head">
              <span class="node-index">0{{ index + 1 }}</span>
              <span class="node-name">{{ step.name }}</span>
              <span
                class="status-pill"
                :class="step.status === 'finished' ? 'pill-finished' : 'pill-running'"
              >
                {{ step.status === 'finished' ? '已完成' : '进行中...' }}
              </span>
            </div>
            <div v-if="step.detail" class="node-detail">
              {{ step.detail }}
            </div>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.pipeline-container {
  margin-bottom: 14px;
  background: rgba(15, 23, 42, 0.5);
  border: 1px solid var(--app-border);
  border-radius: 10px;
  overflow: hidden;
  transition: all 0.2s ease;
}

html:not(.dark) .pipeline-container {
  background: #f8fafc;
}

.pipeline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: rgba(255, 255, 255, 0.02);
  border-bottom: 1px solid var(--app-border-subtle);
  cursor: pointer;
  user-select: none;
  transition: background 0.2s ease;
}

.pipeline-header:hover {
  background: rgba(255, 255, 255, 0.04);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.pipeline-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: rgba(56, 189, 248, 0.12);
  color: var(--app-primary);
  font-size: 14px;
}

.pipeline-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--app-text-primary);
}

.step-counter {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  background: rgba(56, 189, 248, 0.1);
  color: var(--app-primary);
  border-radius: 9999px;
  border: 1px solid rgba(56, 189, 248, 0.2);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--app-text-muted);
  font-size: 12px;
}

.expand-icon {
  font-size: 12px;
}

.steps-wrapper {
  padding: 14px 16px 8px;
  display: flex;
  flex-direction: column;
}

.step-node {
  display: flex;
  gap: 14px;
  position: relative;
}

.node-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 20px;
  flex-shrink: 0;
}

.node-indicator {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2;
}

.icon-finished {
  font-size: 18px;
  color: var(--app-accent-emerald);
  filter: drop-shadow(0 0 6px rgba(16, 185, 129, 0.4));
}

.icon-running {
  font-size: 18px;
  color: var(--app-primary);
  filter: drop-shadow(0 0 6px var(--app-primary-glow));
}

.rail-line {
  flex: 1;
  width: 2px;
  min-height: 24px;
  background: var(--app-border);
  margin: 3px 0;
}

.step-node.is-finished .rail-line {
  background: linear-gradient(to bottom, rgba(16, 185, 129, 0.4), var(--app-border));
}

.node-content {
  flex: 1;
  padding-bottom: 14px;
}

.node-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.node-index {
  font-size: 11px;
  font-family: var(--app-font-mono);
  color: var(--app-text-muted);
}

.node-name {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--app-text-primary);
}

.status-pill {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 4px;
}

.pill-finished {
  background: rgba(16, 185, 129, 0.12);
  color: #10b981;
  border: 1px solid rgba(16, 185, 129, 0.25);
}

.pill-running {
  background: rgba(56, 189, 248, 0.12);
  color: #38bdf8;
  border: 1px solid rgba(56, 189, 248, 0.3);
  animation: pulse-ring 2s infinite ease-in-out;
}

.node-detail {
  font-size: 12px;
  line-height: 1.55;
  color: var(--app-text-secondary);
  background: rgba(0, 0, 0, 0.18);
  border: 1px solid var(--app-border-subtle);
  padding: 6px 10px;
  border-radius: 6px;
  margin-top: 4px;
  font-family: var(--app-font-mono);
  word-break: break-all;
}

html:not(.dark) .node-detail {
  background: #ffffff;
}

.pipeline-collapse-enter-active,
.pipeline-collapse-leave-active {
  transition: all 0.25s ease-out;
}

.pipeline-collapse-enter-from,
.pipeline-collapse-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
