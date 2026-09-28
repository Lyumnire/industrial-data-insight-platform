<!-- AI-assisted -->
<!-- 单资源知识列表面板：支持业务域/状态筛选、高质感字段呈现与 CRUD 对话框。 -->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { describeHttpError } from '../../api/http'
import {
  createKnowledgeItem,
  deleteKnowledgeItem,
  listKnowledge,
  updateKnowledgeItem,
} from '../../api/knowledge'
import { asMetricItem, asObjectItem, asRuleItem, asTopicItem } from '../../api/knowledge'
import {
  DOMAIN_OPTIONS,
  RESOURCE_LABELS,
  STATUS_OPTIONS,
  type KnowledgeItem,
  type KnowledgeRequest,
  type KnowledgeResource,
} from '../../types/knowledge'
import KnowledgeFormDialog from './KnowledgeFormDialog.vue'
import { Plus, Search, Edit, Delete } from '@element-plus/icons-vue'

const props = defineProps<{
  resource: KnowledgeResource
  reloadTick?: number
}>()

const emit = defineEmits<{
  (e: 'changed'): void
}>()

const records = ref<KnowledgeItem[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const loading = ref(false)
const error = ref('')
const domainFilter = ref('')
const statusFilter = ref('')

const dialogVisible = ref(false)
const editingItem = ref<KnowledgeItem | null>(null)

const showDomainFilter = computed(() => props.resource !== 'rules')

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const pageResult = await listKnowledge(props.resource, {
      domain: showDomainFilter.value ? domainFilter.value : undefined,
      status: statusFilter.value,
      page: page.value,
      size: size.value,
    })
    records.value = pageResult.records
    total.value = pageResult.total
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

function onPageChange(p: number): void {
  page.value = p
  void load()
}

function onSizeChange(s: number): void {
  size.value = s
  page.value = 1
  void load()
}

function openCreate(): void {
  editingItem.value = null
  dialogVisible.value = true
}

function openEdit(row: KnowledgeItem): void {
  editingItem.value = row
  dialogVisible.value = true
}

async function handleDelete(row: KnowledgeItem): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认删除${RESOURCE_LABELS[props.resource]}「${row.name}」（${row.code}）？此操作不可撤销。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteKnowledgeItem(props.resource, row.id)
    ElMessage.success('删除成功')
    emit('changed')
    await load()
  } catch (err) {
    error.value = describeHttpError(err)
    ElMessage.error(error.value)
  }
}

async function handleSubmit(body: KnowledgeRequest, editingId: number | null): Promise<void> {
  try {
    if (editingId == null) {
      await createKnowledgeItem(props.resource, body)
      ElMessage.success('新建成功')
    } else {
      await updateKnowledgeItem(props.resource, editingId, body)
      ElMessage.success('更新成功')
    }
    dialogVisible.value = false
    emit('changed')
    await load()
  } catch (err) {
    ElMessage.error(describeHttpError(err))
  }
}

function cellText(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) return value.length > 0 ? value.join('、') : '—'
  return String(value)
}

function domainOf(row: KnowledgeItem): string {
  if (props.resource === 'rules') return '—'
  const itemWithDomain = row as { domain?: unknown }
  return cellText(itemWithDomain.domain)
}

function descriptionOf(row: KnowledgeItem): string {
  if (props.resource === 'rules') {
    return cellText(asRuleItem(row).content)
  }
  return cellText(asObjectItem(row).description)
}

function extraOf(row: KnowledgeItem): string {
  if (props.resource === 'metrics') {
    const m = asMetricItem(row)
    return `${cellText(m.formulaSql)}${m.unit ? `（${m.unit}）` : ''}`
  }
  if (props.resource === 'rules') {
    const r = asRuleItem(row)
    return cellText(r.ruleType)
  }
  if (props.resource === 'topics') {
    const t = asTopicItem(row)
    return `对象:${cellText(t.relatedObjectIds)} / 指标:${cellText(t.relatedMetricIds)}`
  }
  return ''
}

const extraLabel = computed(() => {
  if (props.resource === 'metrics') return '计算公式 / 单位'
  if (props.resource === 'rules') return '规则类型'
  if (props.resource === 'topics') return '关联实体拓扑'
  return ''
})

onMounted(() => {
  void load()
})

watch(
  () => props.reloadTick,
  () => {
    void load()
  },
)
</script>

<template>
  <div class="knowledge-panel">
    <div class="panel-toolbar">
      <div class="filters-group">
        <el-select
          v-if="showDomainFilter"
          v-model="domainFilter"
          clearable
          filterable
          placeholder="业务域筛选"
          class="filter-select"
          @change="resetAndLoad"
        >
          <el-option v-for="d in DOMAIN_OPTIONS" :key="d" :label="d" :value="d" />
        </el-select>

        <el-select
          v-model="statusFilter"
          clearable
          filterable
          placeholder="状态筛选"
          class="filter-select"
          @change="resetAndLoad"
        >
          <el-option v-for="s in STATUS_OPTIONS" :key="s" :label="s" :value="s" />
        </el-select>

        <el-button class="query-btn" @click="resetAndLoad">
          <el-icon><Search /></el-icon>
          <span>查询</span>
        </el-button>
      </div>

      <div class="actions-group">
        <span class="total-badge">共 {{ total }} 条记录</span>
        <el-button type="primary" class="create-btn" @click="openCreate">
          <el-icon><Plus /></el-icon>
          <span>新建{{ RESOURCE_LABELS[resource] }}</span>
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="error"
      class="block-gap"
      type="error"
      show-icon
      :closable="false"
      :title="error"
    />

    <div class="table-frame">
      <el-table
        v-loading="loading"
        :data="records"
        border
        stripe
        size="small"
        class="custom-table"
      >
        <el-table-column prop="code" label="业务编码" min-width="150" show-overflow-tooltip>
          <template #default="scope">
            <span class="code-pill">{{ scope.row.code }}</span>
          </template>
        </el-table-column>

        <el-table-column prop="name" label="实体名称" min-width="150" show-overflow-tooltip>
          <template #default="scope">
            <span class="name-text">{{ scope.row.name }}</span>
          </template>
        </el-table-column>

        <el-table-column
          v-if="showDomainFilter"
          label="业务域"
          width="110"
        >
          <template #default="scope">
            <el-tag size="small" effect="plain" class="domain-tag">
              {{ domainOf(scope.row as KnowledgeItem) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="描述 / 规则内容" min-width="200" show-overflow-tooltip>
          <template #default="scope">
            <span class="desc-text">{{ descriptionOf(scope.row as KnowledgeItem) }}</span>
          </template>
        </el-table-column>

        <el-table-column
          v-if="extraLabel"
          :label="extraLabel"
          min-width="180"
          show-overflow-tooltip
        >
          <template #default="scope">
            <span class="extra-cell">{{ extraOf(scope.row as KnowledgeItem) }}</span>
          </template>
        </el-table-column>

        <el-table-column prop="status" label="状态" width="90" align="center">
          <template #default="scope">
            <span
              class="status-indicator-tag"
              :class="scope.row.status === 'active' ? 'is-active' : 'is-inactive'"
            >
              {{ scope.row.status === 'active' ? '启用' : '禁用' }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="120" fixed="right" align="center">
          <template #default="scope">
            <el-button
              size="small"
              text
              type="primary"
              @click="openEdit(scope.row as KnowledgeItem)"
            >
              <el-icon><Edit /></el-icon>
              <span>编辑</span>
            </el-button>
            <el-button
              size="small"
              text
              type="danger"
              @click="handleDelete(scope.row as KnowledgeItem)"
            >
              <el-icon><Delete /></el-icon>
              <span>删除</span>
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="pagination-footer">
      <el-pagination
        :current-page="page"
        :page-size="size"
        :page-sizes="[10, 20, 50]"
        :total="total"
        layout="total, sizes, prev, pager, next"
        size="small"
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </div>

    <KnowledgeFormDialog
      :visible="dialogVisible"
      :resource="resource"
      :item="editingItem"
      @update:visible="(v) => (dialogVisible = v)"
      @submit="handleSubmit"
    />
  </div>
</template>

<style scoped>
.knowledge-panel {
  display: flex;
  flex-direction: column;
}

.panel-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 0 16px;
  gap: 16px;
  flex-wrap: wrap;
}

.filters-group {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.filter-select {
  width: 150px;
}

.query-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.actions-group {
  display: flex;
  align-items: center;
  gap: 12px;
}

.total-badge {
  font-size: 12px;
  color: var(--app-text-muted);
}

.create-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--app-gradient-primary);
  border: none;
  font-weight: 600;
}

.table-frame {
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--app-border);
}

.code-pill {
  font-family: var(--app-font-mono);
  font-size: 11.5px;
  color: var(--app-primary);
  background: rgba(56, 189, 248, 0.08);
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid rgba(56, 189, 248, 0.2);
}

.name-text {
  font-weight: 600;
  color: var(--app-text-primary);
}

.desc-text {
  color: var(--app-text-secondary);
}

.extra-cell {
  font-family: var(--app-font-mono);
  font-size: 11.5px;
  color: #a5b4fc;
}

.status-indicator-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}

.status-indicator-tag.is-active {
  background: rgba(16, 185, 129, 0.12);
  color: #10b981;
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.status-indicator-tag.is-inactive {
  background: rgba(148, 163, 184, 0.1);
  color: #94a3b8;
  border: 1px solid rgba(148, 163, 184, 0.2);
}

.pagination-footer {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

.block-gap {
  margin-bottom: 12px;
}
</style>
