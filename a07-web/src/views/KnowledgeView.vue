<!-- AI-assisted -->
<!-- F2 业务知识中心：四维实体资源（对象/指标/规则/主题）Tab 切换与知识图谱入口。 -->
<script setup lang="ts">
import { ref } from 'vue'
import AppNav from '../components/AppNav.vue'
import KnowledgeResourcePanel from '../components/knowledge/KnowledgeResourcePanel.vue'
import type { KnowledgeResource } from '../types/knowledge'
import {
  Collection,
  TrendCharts,
  DocumentChecked,
  Aim,
  Share,
} from '@element-plus/icons-vue'

const activeTab = ref<KnowledgeResource>('objects')
const reloadTick = ref(0)

function onResourceChanged(): void {
  reloadTick.value += 1
}
</script>

<template>
  <div class="knowledge-page">
    <AppNav />

    <header class="page-header-banner">
      <div class="banner-inner">
        <div class="banner-title-area">
          <div class="banner-icon">
            <el-icon><Collection /></el-icon>
          </div>
          <div>
            <h1 class="page-title">业务知识中心</h1>
            <p class="page-sub">
              统一维护制造业务实体、核心业务指标、业务约束规则与分析主题
            </p>
          </div>
        </div>

        <div class="banner-actions">
          <router-link to="/knowledge/graph" class="graph-nav-btn">
            <el-icon><Share /></el-icon>
            <span>进入知识图谱</span>
            <span class="btn-arrow">→</span>
          </router-link>
        </div>
      </div>
    </header>

    <main class="page-main-container">
      <div class="tabs-card">
        <el-tabs v-model="activeTab" class="custom-knowledge-tabs">
          <el-tab-pane name="objects">
            <template #label>
              <span class="tab-label-custom">
                <el-icon><Collection /></el-icon>
                <span>业务对象 (Objects)</span>
              </span>
            </template>
            <KnowledgeResourcePanel
              resource="objects"
              :reload-tick="reloadTick"
              @changed="onResourceChanged"
            />
          </el-tab-pane>

          <el-tab-pane name="metrics">
            <template #label>
              <span class="tab-label-custom">
                <el-icon><TrendCharts /></el-icon>
                <span>业务指标 (Metrics)</span>
              </span>
            </template>
            <KnowledgeResourcePanel
              resource="metrics"
              :reload-tick="reloadTick"
              @changed="onResourceChanged"
            />
          </el-tab-pane>

          <el-tab-pane name="rules">
            <template #label>
              <span class="tab-label-custom">
                <el-icon><DocumentChecked /></el-icon>
                <span>业务规则 (Rules)</span>
              </span>
            </template>
            <KnowledgeResourcePanel
              resource="rules"
              :reload-tick="reloadTick"
              @changed="onResourceChanged"
            />
          </el-tab-pane>

          <el-tab-pane name="topics">
            <template #label>
              <span class="tab-label-custom">
                <el-icon><Aim /></el-icon>
                <span>分析主题 (Topics)</span>
              </span>
            </template>
            <KnowledgeResourcePanel
              resource="topics"
              :reload-tick="reloadTick"
              @changed="onResourceChanged"
            />
          </el-tab-pane>
        </el-tabs>
      </div>
    </main>
  </div>
</template>

<style scoped>
.knowledge-page {
  min-height: 100vh;
  background: var(--app-bg-deep);
  display: flex;
  flex-direction: column;
}

.page-header-banner {
  background: var(--app-bg-surface);
  border-bottom: 1px solid var(--app-border);
  padding: 18px 32px;
}

.banner-inner {
  max-width: 1360px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.banner-title-area {
  display: flex;
  align-items: center;
  gap: 14px;
}

.banner-icon {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  background: rgba(56, 189, 248, 0.12);
  border: 1px solid rgba(56, 189, 248, 0.28);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: var(--app-primary);
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

.graph-nav-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: linear-gradient(135deg, rgba(56, 189, 248, 0.15) 0%, rgba(99, 102, 241, 0.15) 100%);
  border: 1px solid rgba(56, 189, 248, 0.35);
  border-radius: 8px;
  color: var(--app-primary);
  font-size: 13.5px;
  font-weight: 600;
  text-decoration: none;
  box-shadow: 0 2px 10px rgba(56, 189, 248, 0.15);
  transition: all 0.25s ease;
}

.graph-nav-btn:hover {
  background: linear-gradient(135deg, rgba(56, 189, 248, 0.25) 0%, rgba(99, 102, 241, 0.25) 100%);
  border-color: var(--app-primary);
  transform: translateY(-1px);
}

.btn-arrow {
  transition: transform 0.2s ease;
}

.graph-nav-btn:hover .btn-arrow {
  transform: translateX(3px);
}

.page-main-container {
  max-width: 1360px;
  width: 100%;
  margin: 0 auto;
  padding: 24px 32px 40px;
  flex: 1;
}

.tabs-card {
  background: var(--app-bg-card);
  border: 1px solid var(--app-border);
  border-radius: 12px;
  box-shadow: var(--app-shadow-card);
  padding: 12px 20px 20px;
}

.tab-label-custom {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
}
</style>
