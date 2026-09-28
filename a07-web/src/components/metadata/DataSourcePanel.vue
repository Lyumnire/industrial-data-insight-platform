<!-- AI-assisted -->
<!-- 数据源列表面板：数据源连通测试、元数据采集调度、编辑与安全密码保护。 -->
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { describeHttpError } from '../../api/http'
import {
  deleteDataSource,
  listDataSources,
  refreshDataSource,
  testDataSource,
} from '../../api/metadata'
import {
  DATASOURCE_STATUS_OPTIONS,
  type DataSourceItem,
  type RefreshResult,
} from '../../types/metadata'
import DataSourceFormDialog from './DataSourceFormDialog.vue'
import {
  Plus,
  Search,
  Check,
  Refresh,
  Edit,
  Delete,
  Coin,
  CircleCheck,
} from '@element-plus/icons-vue'

const props = defineProps<{
  selectedId: number | null
}>()

const emit = defineEmits<{
  (e: 'select', id: number | null): void
  (e: 'refreshed', id: number): void
}>()

const records = ref<DataSourceItem[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const statusFilter = ref('')
const loading = ref(false)
const error = ref('')
const busyId = ref<number | null>(null)

const dialogVisible = ref(false)
const editing = ref<DataSourceItem | null>(null)
const lastRefresh = ref<RefreshResult | null>(null)

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const result = await listDataSources({
      status: statusFilter.value,
      page: page.value,
      size: size.value,
    })
    records.value = result.records
    total.value = result.total
  } catch (err) {
    records.value = []
    total.value = 0
    error.value = describeHttpError(err)
  } finally {
    loading.value = false
  }
}

function resetAndLoad(): void {
  page.value = 1
  void load()
}

function openCreate(): void {
  editing.value = null
  dialogVisible.value = true
}

function openEdit(row: DataSourceItem): void {
  editing.value = row
  dialogVisible.value = true
}

async function handleTestRow(row: DataSourceItem): Promise<void> {
  busyId.value = row.id
  try {
    const result = await testDataSource(row.id)
    if (result.connected) {
      ElMessage.success(
        `连接测试成功：${result.message}${result.tableCount != null ? `（检测到 ${result.tableCount} 张表）` : ''}`,
      )
    } else {
      ElMessage.warning(`连接失败：${result.message}`)
    }
  } catch (err) {
    ElMessage.error(describeHttpError(err))
  } finally {
    busyId.value = null
  }
}

async function handleRefresh(row: DataSourceItem): Promise<void> {
  busyId.value = row.id
  try {
    const result = await refreshDataSource(row.id)
    lastRefresh.value = result
    ElMessage.success(
      `采集完成：表 ${result.tableCount} / 列 ${result.columnCount} / 关系 ${result.relationshipCount}` +
        (result.reindexNotified ? '（已通知引擎 Chroma 重构索引）' : ''),
    )
    emit('refreshed', row.id)
  } catch (err) {
    ElMessage.error(describeHttpError(err))
  } finally {
    busyId.value = null
  }
}

async function handleDelete(row: DataSourceItem): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认删除数据源「${row.name}」？已采集的元数据将一并清理。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteDataSource(row.id)
    ElMessage.success('数据源已删除')
    if (props.selectedId === row.id) emit('select', null)
    await load()
  } catch (err) {
    ElMessage.error(describeHttpError(err))
  }
}

function selectRow(row: DataSourceItem): void {
  emit('select', row.id)
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="ds-panel">
    <div class="panel-toolbar">
      <div class="filter-wrap">
        <el-select
          v-model="statusFilter"
          clearable
          placeholder="状态筛选"
          class="filter-select"
          @change="resetAndLoad"
        >
          <el-option v-for="s in DATASOURCE_STATUS_OPTIONS" :key="s" :label="s" :value="s" />
        </el-select>
        <el-button class="query-btn" @click="resetAndLoad">
          <el-icon><Search /></el-icon>
          <span>查询</span>
        </el-button>
      </div>

      <div class="action-wrap">
        <el-button type="primary" class="create-btn" @click="openCreate">
          <el-icon><Plus /></el-icon>
          <span>注册数据源</span>
        </el-button>
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

    <div class="table-frame">
      <el-table
        v-loading="loading"
        :data="records"
        border
        stripe
        size="small"
        highlight-current-row
        class="custom-table"
        @row-click="selectRow"
      >
        <el-table-column prop="name" label="数据源名称" min-width="120" show-overflow-tooltip>
          <template #default="scope">
            <div class="ds-name-cell">
              <el-icon class="ds-icon"><Coin /></el-icon>
              <span class="ds-name">{{ scope.row.name }}</span>
              <el-tag
                v-if="props.selectedId === scope.row.id"
                size="small"
                type="primary"
                effect="dark"
                class="current-tag"
              >
                当前浏览
              </el-tag>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="dbType" label="引擎类型" width="85" align="center">
          <template #default="scope">
            <span class="db-pill">{{ scope.row.dbType }}</span>
          </template>
        </el-table-column>

        <el-table-column prop="jdbcUrl" label="JDBC 连接串" min-width="150" show-overflow-tooltip>
          <template #default="scope">
            <span class="url-text">{{ scope.row.jdbcUrl }}</span>
          </template>
        </el-table-column>

        <el-table-column prop="status" label="状态" width="75" align="center">
          <template #default="scope">
            <span
              class="status-dot-tag"
              :class="scope.row.status === 'active' ? 'is-active' : 'is-inactive'"
            >
              {{ scope.row.status === 'active' ? '启用' : '禁用' }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="190" fixed="right" align="center">
          <template #default="scope">
            <div class="action-cell">
              <el-button
                size="small"
                text
                type="primary"
                class="op-btn"
                :loading="busyId === (scope.row as DataSourceItem).id"
                @click.stop="handleTestRow(scope.row as DataSourceItem)"
              >
                <el-icon><Check /></el-icon>
                <span>测试</span>
              </el-button>

              <el-button
                size="small"
                text
                type="warning"
                class="op-btn"
                :loading="busyId === (scope.row as DataSourceItem).id"
                @click.stop="handleRefresh(scope.row as DataSourceItem)"
              >
                <el-icon><Refresh /></el-icon>
                <span>采集</span>
              </el-button>

              <el-tooltip content="编辑数据源" placement="top">
                <el-button
                  size="small"
                  text
                  type="primary"
                  class="op-icon-btn"
                  @click.stop="openEdit(scope.row as DataSourceItem)"
                >
                  <el-icon><Edit /></el-icon>
                </el-button>
              </el-tooltip>

              <el-tooltip content="删除数据源" placement="top">
                <el-button
                  size="small"
                  text
                  type="danger"
                  class="op-icon-btn"
                  @click.stop="handleDelete(scope.row as DataSourceItem)"
                >
                  <el-icon><Delete /></el-icon>
                </el-button>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>

        <template #empty>
          <el-empty
            :description="error ? '加载失败，请检查服务状态' : '暂无数据源，请点击上方注册数据源'"
            :image-size="60"
          />
        </template>
      </el-table>
    </div>

    <!-- 最近采集成功反馈卡 -->
    <div v-if="lastRefresh" class="refresh-status-banner">
      <el-icon><CircleCheck /></el-icon>
      <div class="refresh-status-content">
        <span class="refresh-main-text">
          采集成功：发现 <strong>{{ lastRefresh.tableCount }}</strong> 张表、
          <strong>{{ lastRefresh.columnCount }}</strong> 个字段、
          <strong>{{ lastRefresh.relationshipCount }}</strong> 条拓扑关系
        </span>
        <span v-if="lastRefresh.reindexNotified" class="reindex-ok-text">
          · Chroma 向量索引同步完成
        </span>
      </div>
    </div>

    <div class="pager-wrap">
      <el-pagination
        layout="total, prev, pager, next"
        :total="total"
        :page-size="size"
        :current-page="page"
        size="small"
        @current-change="(p: number) => { page = p; void load() }"
      />
    </div>

    <DataSourceFormDialog
      v-model:visible="dialogVisible"
      :item="editing"
      @saved="load"
    />
  </div>
</template>

<style scoped>
.ds-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.panel-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.filter-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.filter-select {
  width: 130px;
}

.query-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.create-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--app-primary) !important;
  border-color: var(--app-primary) !important;
  font-weight: 600;
}

.table-frame {
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--app-border);
}

.ds-name-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.ds-icon {
  color: #10b981;
  font-size: 14px;
}

.ds-name {
  font-weight: 600;
  color: var(--app-text-primary);
}

.current-tag {
  font-size: 10px;
  padding: 0 4px;
  height: 18px;
  line-height: 16px;
}

.db-pill {
  font-family: var(--app-font-mono);
  font-size: 11px;
  color: var(--app-primary);
  background: rgba(56, 189, 248, 0.08);
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid rgba(56, 189, 248, 0.2);
}

.url-text {
  font-family: var(--app-font-mono);
  font-size: 11.5px;
  color: var(--app-text-muted);
}

.status-dot-tag {
  font-size: 10.5px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
}

.status-dot-tag.is-active {
  background: rgba(16, 185, 129, 0.12);
  color: #10b981;
}

.status-dot-tag.is-inactive {
  background: rgba(148, 163, 184, 0.1);
  color: #94a3b8;
}

.action-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 2px;
}

.op-btn {
  padding: 3px 5px !important;
  font-size: 12px;
}

.op-icon-btn {
  padding: 3px 4px !important;
  font-size: 13px;
}

:deep(.el-table__fixed-right),
:deep(.el-table__fixed-right .el-table__cell) {
  background-color: var(--app-bg-card) !important;
}

:deep(.el-table__fixed-right th.el-table__cell),
:deep(.el-table__fixed-right-patch) {
  background-color: #162032 !important;
}

html:not(.dark) :deep(.el-table__fixed-right),
html:not(.dark) :deep(.el-table__fixed-right .el-table__cell) {
  background-color: #ffffff !important;
}

html:not(.dark) :deep(.el-table__fixed-right th.el-table__cell),
html:not(.dark) :deep(.el-table__fixed-right-patch) {
  background-color: #f8fafc !important;
}

.refresh-status-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.25);
  border-radius: 8px;
  color: #10b981;
  font-size: 12px;
}

.refresh-main-text strong {
  color: #34d399;
}

.reindex-ok-text {
  color: var(--app-primary);
  font-weight: 600;
}

.pager-wrap {
  display: flex;
  justify-content: flex-end;
}

.block-gap {
  margin: 0;
}
</style>
