<!-- AI-assisted -->
<!-- 知识图谱视图：展示业务实体拓扑网络、概览统计 KPI、边类型筛选与节点详细档案。 -->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppNav from '../components/AppNav.vue'
import KnowledgeGraphSvg from '../components/knowledge/KnowledgeGraphSvg.vue'
import { fetchKnowledgeGraph } from '../api/knowledge'
import { describeHttpError } from '../api/http'
import type { GraphEdge, GraphNode } from '../types/knowledge'
import {
  Share,
  Refresh,
  ArrowLeft,
  Collection,
  TrendCharts,
  DocumentChecked,
  Aim,
} from '@element-plus/icons-vue'

const nodes = ref<GraphNode[]>([])
const edges = ref<GraphEdge[]>([])
const loading = ref(false)
const error = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const graph = await fetchKnowledgeGraph()
    nodes.value = graph.nodes
    edges.value = graph.edges
  } catch (err) {
    nodes.value = []
    edges.value = []
    error.value = describeHttpError(err)
  } finally {
    loading.value = false
  }
}

const objectCount = computed(() => nodes.value.filter((n) => n.type === 'object').length)
const metricCount = computed(() => nodes.value.filter((n) => n.type === 'metric').length)
const ruleCount = computed(() => nodes.value.filter((n) => n.type === 'rule').length)
const topicCount = computed(() => nodes.value.filter((n) => n.type === 'topic').length)

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="graph-page">
    <AppNav />

    <header class="page-header-banner">
      <div class="banner-inner">
        <div class="banner-left">
          <div class="banner-icon">
            <el-icon><Share /></el-icon>
          </div>
          <div>
            <h1 class="page-title">业务知识图谱</h1>
            <p class="page-sub">
              业务实体、核心指标、规则与分析主题的多维拓扑关联可视化
            </p>
          </div>
        </div>

        <div class="banner-actions">
          <button class="tool-btn" :disabled="loading" @click="load">
            <el-icon :class="{ 'is-loading': loading }"><Refresh /></el-icon>
            <span>刷新图谱</span>
          </button>
          <router-link to="/knowledge" class="back-link">
            <el-icon><ArrowLeft /></el-icon>
            <span>返回知识中心</span>
          </router-link>
        </div>
      </div>
    </header>

    <main class="page-main-container" v-loading="loading">
      <!-- 统计指标 KPI 条 -->
      <div class="kpi-strip">
        <div class="kpi-card">
          <span class="kpi-label">图谱节点总数</span>
          <span class="kpi-val">{{ nodes.length }}</span>
        </div>
        <div class="kpi-card">
          <span class="kpi-label">拓扑关系边数</span>
          <span class="kpi-val val-blue">{{ edges.length }}</span>
        </div>
        <div class="kpi-card">
          <div class="kpi-head">
            <el-icon color="#38bdf8"><Collection /></el-icon>
            <span class="kpi-label">业务对象</span>
          </div>
          <span class="kpi-val val-cyan">{{ objectCount }}</span>
        </div>
        <div class="kpi-card">
          <div class="kpi-head">
            <el-icon color="#10b981"><TrendCharts /></el-icon>
            <span class="kpi-label">业务指标</span>
          </div>
          <span class="kpi-val val-green">{{ metricCount }}</span>
        </div>
        <div class="kpi-card">
          <div class="kpi-head">
            <el-icon color="#f59e0b"><DocumentChecked /></el-icon>
            <span class="kpi-label">业务规则</span>
          </div>
          <span class="kpi-val val-amber">{{ ruleCount }}</span>
        </div>
        <div class="kpi-card">
          <div class="kpi-head">
            <el-icon color="#a855f7"><Aim /></el-icon>
            <span class="kpi-label">分析主题</span>
          </div>
          <span class="kpi-val val-purple">{{ topicCount }}</span>
        </div>
      </div>

      <el-alert
        v-if="error"
        type="error"
        show-icon
        :closable="false"
        :title="error"
        class="block-gap"
      />

      <div class="graph-card-wrap">
        <KnowledgeGraphSvg
          v-if="!error && (nodes.length > 0 || edges.length > 0)"
          :nodes="nodes"
          :edges="edges"
        />
        <el-empty
          v-else-if="!error"
          description="暂无图谱数据（可在知识中心新建主题/规则并关联实体后查看）"
        />
      </div>
    </main>
  </div>
</template>

<style scoped>
.graph-page {
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
  max-width: 1400px;
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
  gap: 12px;
}

.tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--app-border);
  border-radius: 6px;
  color: var(--app-text-primary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.tool-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  border-color: var(--app-primary);
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  color: var(--app-text-secondary);
  text-decoration: none;
  font-size: 13px;
  border-radius: 6px;
  transition: all 0.2s ease;
}

.back-link:hover {
  color: var(--app-primary);
  background: rgba(255, 255, 255, 0.04);
}

.page-main-container {
  max-width: 1400px;
  width: 100%;
  margin: 0 auto;
  padding: 20px 32px 36px;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.kpi-strip {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
}

.kpi-card {
  background: var(--app-bg-card);
  border: 1px solid var(--app-border);
  border-radius: 10px;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.kpi-head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.kpi-label {
  font-size: 11.5px;
  color: var(--app-text-muted);
}

.kpi-val {
  font-size: 20px;
  font-weight: 700;
  font-family: var(--app-font-mono);
  color: var(--app-text-primary);
}

.val-blue { color: #38bdf8; }
.val-cyan { color: #06b6d4; }
.val-green { color: #10b981; }
.val-amber { color: #f59e0b; }
.val-purple { color: #c084fc; }

.graph-card-wrap {
  background: var(--app-bg-card);
  border: 1px solid var(--app-border);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: var(--app-shadow-card);
}

.block-gap {
  margin-bottom: 8px;
}

@media (max-width: 1024px) {
  .kpi-strip {
    grid-template-columns: repeat(3, 1fr);
  }
}
</style>
