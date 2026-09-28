<!-- AI-assisted -->
<!-- F3 数据资源中心：数据源管理 + 表/字段/关系浏览器 + Chroma 向量索引同步。 -->
<script setup lang="ts">
import { ref } from 'vue'
import AppNav from '../components/AppNav.vue'
import DataSourcePanel from '../components/metadata/DataSourcePanel.vue'
import MetaBrowser from '../components/metadata/MetaBrowser.vue'
import { describeHttpError } from '../api/http'
import { triggerReindex } from '../api/metadata'
import { ElMessage } from 'element-plus'
import { Coin, Refresh } from '@element-plus/icons-vue'

const selectedDataSourceId = ref<number | null>(null)
const refreshTick = ref(0)
const reindexing = ref(false)
const reindexError = ref('')

function onSelect(id: number | null): void {
  selectedDataSourceId.value = id
}

function onRefreshed(id: number): void {
  selectedDataSourceId.value = id
  refreshTick.value += 1
}

async function handleReindex(): Promise<void> {
  reindexing.value = true
  reindexError.value = ''
  try {
    const ok = await triggerReindex()
    if (ok) {
      ElMessage.success('知识与元数据检索索引已更新')
    } else {
      ElMessage.warning('索引同步请求已发送，引擎暂未响应')
    }
  } catch (err) {
    reindexError.value = describeHttpError(err)
    ElMessage.error(reindexError.value)
  } finally {
    reindexing.value = false
  }
}
</script>

<template>
  <div class="metadata-page">
    <AppNav />

    <header class="page-header-banner">
      <div class="banner-inner">
        <div class="banner-left">
          <div class="banner-icon">
            <el-icon><Coin /></el-icon>
          </div>
          <div>
            <h1 class="page-title">数据资源中心</h1>
            <p class="page-sub">
              统一管理企业数据源连接与库表元数据资产，支持结构同步与字段检索
            </p>
          </div>
        </div>

        <div class="banner-actions">
          <el-tooltip content="重新构建元数据与知识检索索引" placement="bottom">
            <button class="reindex-btn" :disabled="reindexing" @click="handleReindex">
              <el-icon :class="{ 'is-loading': reindexing }"><Refresh /></el-icon>
              <span>{{ reindexing ? '同步中...' : '同步知识索引' }}</span>
            </button>
          </el-tooltip>
        </div>
      </div>
    </header>

    <main class="page-main-container">
      <el-alert
        v-if="reindexError"
        type="error"
        show-icon
        :closable="false"
        :title="reindexError"
        class="block-gap"
      />

      <div class="meta-dual-grid">
        <!-- 左侧：数据源面板 -->
        <div class="pane-card ds-card">
          <div class="card-head">
            <span class="card-title">数据源连接池</span>
            <span class="sub-hint">点击行选中并在右侧浏览</span>
          </div>
          <div class="card-body">
            <DataSourcePanel
              :selected-id="selectedDataSourceId"
              @select="onSelect"
              @refreshed="onRefreshed"
            />
          </div>
        </div>

        <!-- 右侧：元数据多维浏览器 -->
        <div class="pane-card browser-card">
          <div class="card-body">
            <MetaBrowser
              :data-source-id="selectedDataSourceId"
              :refresh-tick="refreshTick"
            />
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.metadata-page {
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
  max-width: 1560px;
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
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: #10b981;
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

.reindex-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 16px;
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.35);
  border-radius: 8px;
  color: #10b981;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.25s ease;
}

.reindex-btn:hover:not(:disabled) {
  background: rgba(16, 185, 129, 0.22);
  border-color: #10b981;
}

.page-main-container {
  max-width: 1560px;
  width: 100%;
  margin: 0 auto;
  padding: 20px 32px 36px;
  flex: 1;
}

.meta-dual-grid {
  display: grid;
  grid-template-columns: minmax(520px, 1.15fr) minmax(460px, 1fr);
  gap: 20px;
  align-items: start;
}

.pane-card {
  background: var(--app-bg-card);
  border: 1px solid var(--app-border);
  border-radius: 12px;
  box-shadow: var(--app-shadow-card);
  overflow: hidden;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 18px;
  background: rgba(255, 255, 255, 0.02);
  border-bottom: 1px solid var(--app-border);
}

.card-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--app-text-primary);
}

.sub-hint {
  font-size: 11px;
  color: var(--app-text-muted);
}

.card-body {
  padding: 16px;
}

.block-gap {
  margin-bottom: 12px;
}

@media (max-width: 1024px) {
  .meta-dual-grid {
    grid-template-columns: 1fr;
  }
}
</style>
