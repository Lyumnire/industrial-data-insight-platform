<!-- AI-assisted -->
<!-- 表/字段/关系浏览器：按选中数据源拉取数据表（含中文注释）、字段结构（主键/类型/样例）与外键关系拓扑。 -->
<script setup lang="ts">
import { ref, watch } from 'vue'
import { describeHttpError } from '../../api/http'
import { listColumns, listRelationships, listTables } from '../../api/metadata'
import type {
  ColumnMetadataItem,
  RelationshipItem,
  TableMetadataItem,
} from '../../types/metadata'
import {
  Grid,
  Tickets,
  Share,
  Search,
  Key,
  Right,
  Close,
} from '@element-plus/icons-vue'

const props = defineProps<{
  dataSourceId: number | null
  refreshTick?: number
}>()

const activeTab = ref<'tables' | 'columns' | 'relationships'>('tables')
const tableNameFilter = ref('')
const selectedTable = ref('')

const tables = ref<TableMetadataItem[]>([])
const tableTotal = ref(0)
const tablePage = ref(1)
const tableSize = ref(20)
const tablesLoading = ref(false)
const tablesError = ref('')

const columns = ref<ColumnMetadataItem[]>([])
const columnTotal = ref(0)
const columnPage = ref(1)
const columnSize = ref(50)
const columnsLoading = ref(false)
const columnsError = ref('')

const relationships = ref<RelationshipItem[]>([])
const relLoading = ref(false)
const relError = ref('')

async function loadTables(): Promise<void> {
  if (props.dataSourceId == null) {
    tables.value = []
    tableTotal.value = 0
    return
  }
  tablesLoading.value = true
  tablesError.value = ''
  try {
    const pageResult = await listTables({
      dataSourceId: props.dataSourceId,
      tableName: tableNameFilter.value,
      page: tablePage.value,
      size: tableSize.value,
    })
    tables.value = pageResult.records
    tableTotal.value = pageResult.total
  } catch (err) {
    tables.value = []
    tableTotal.value = 0
    tablesError.value = describeHttpError(err)
  } finally {
    tablesLoading.value = false
  }
}

async function loadColumns(tableName?: string): Promise<void> {
  if (props.dataSourceId == null) {
    columns.value = []
    columnTotal.value = 0
    return
  }
  const table = tableName ?? selectedTable.value
  columnsLoading.value = true
  columnsError.value = ''
  try {
    const pageResult = await listColumns({
      dataSourceId: props.dataSourceId,
      tableName: table.length > 0 ? table : undefined,
      page: columnPage.value,
      size: columnSize.value,
    })
    columns.value = pageResult.records
    columnTotal.value = pageResult.total
  } catch (err) {
    columns.value = []
    columnTotal.value = 0
    columnsError.value = describeHttpError(err)
  } finally {
    columnsLoading.value = false
  }
}

async function loadRelationships(): Promise<void> {
  if (props.dataSourceId == null) {
    relationships.value = []
    return
  }
  relLoading.value = true
  relError.value = ''
  try {
    relationships.value = await listRelationships(props.dataSourceId)
  } catch (err) {
    relationships.value = []
    relError.value = describeHttpError(err)
  } finally {
    relLoading.value = false
  }
}

function loadAll(): void {
  void loadTables()
  void loadColumns()
  void loadRelationships()
}

function browseTable(row: TableMetadataItem): void {
  selectedTable.value = row.tableName
  activeTab.value = 'columns'
  columnPage.value = 1
  void loadColumns(row.tableName)
}

function clearTableFilter(): void {
  selectedTable.value = ''
  columnPage.value = 1
  void loadColumns('')
}

function sampleText(values: string[] | null | undefined): string {
  if (!Array.isArray(values) || values.length === 0) return '—'
  return values.slice(0, 5).join(' · ')
}

watch(
  () => props.dataSourceId,
  () => {
    selectedTable.value = ''
    tableNameFilter.value = ''
    tablePage.value = 1
    columnPage.value = 1
    loadAll()
  },
  { immediate: true },
)

watch(
  () => props.refreshTick,
  () => {
    loadAll()
  },
)

watch(activeTab, (tab) => {
  if (tab === 'tables') void loadTables()
  else if (tab === 'columns') void loadColumns()
  else void loadRelationships()
})
</script>

<template>
  <div class="meta-browser">
    <div class="browser-head">
      <div class="head-left">
        <span class="head-title">元数据资产总览</span>
        <el-tag v-if="props.dataSourceId != null" size="small" type="primary" effect="dark">
          已连接数据源 #{{ props.dataSourceId }}
        </el-tag>
        <span v-else class="unselected-hint">未选择数据源，请在左侧点击选中</span>
      </div>
    </div>

    <div v-if="props.dataSourceId == null" class="empty-state-banner">
      <el-empty
        description="请在左侧数据源列表点击一行，即可立即浏览该库的表结构、列注释与拓扑关系"
        :image-size="80"
      />
    </div>

    <el-tabs v-else v-model="activeTab" class="browser-tabs">
      <!-- 1. 数据表 Tab -->
      <el-tab-pane name="tables">
        <template #label>
          <span class="tab-label-custom">
            <el-icon><Grid /></el-icon>
            <span>数据表 (Tables)</span>
            <span v-if="tableTotal > 0" class="count-pill">{{ tableTotal }}</span>
          </span>
        </template>

        <div class="sub-toolbar">
          <el-input
            v-model="tableNameFilter"
            placeholder="按表名检索..."
            clearable
            class="table-search-input"
            :prefix-icon="Search"
            @keyup.enter="() => { tablePage = 1; void loadTables() }"
            @clear="() => { tablePage = 1; void loadTables() }"
          />
          <el-button @click="() => { tablePage = 1; void loadTables() }">查询</el-button>
        </div>

        <el-alert
          v-if="tablesError"
          type="error"
          show-icon
          :closable="false"
          :title="tablesError"
          class="block-gap"
        />

        <div class="table-frame">
          <el-table
            v-loading="tablesLoading"
            :data="tables"
            border
            stripe
            size="small"
            class="custom-table"
          >
            <el-table-column prop="tableName" label="数据表名" min-width="160" show-overflow-tooltip>
              <template #default="scope">
                <span class="table-name-code">{{ scope.row.tableName }}</span>
              </template>
            </el-table-column>

            <el-table-column prop="tableComment" label="中文业务注释" min-width="180" show-overflow-tooltip>
              <template #default="scope">
                <span class="comment-text">{{ scope.row.tableComment || '—' }}</span>
              </template>
            </el-table-column>

            <el-table-column prop="tableType" label="类型" width="90" align="center">
              <template #default="scope">
                <el-tag size="small" effect="plain">{{ scope.row.tableType }}</el-tag>
              </template>
            </el-table-column>

            <el-table-column prop="rowCount" label="预估行数" width="100" align="right">
              <template #default="scope">
                <span class="row-num">{{ scope.row.rowCount ?? '—' }}</span>
              </template>
            </el-table-column>

            <el-table-column label="操作" width="100" align="center" fixed="right">
              <template #default="scope">
                <el-button
                  size="small"
                  text
                  type="primary"
                  @click="browseTable(scope.row as TableMetadataItem)"
                >
                  <span>查字段</span>
                  <el-icon class="op-arrow"><Right /></el-icon>
                </el-button>
              </template>
            </el-table-column>

            <template #empty>
              <el-empty
                :description="tablesError ? '加载失败' : '暂无表元数据，请点击左侧「采集」按钮'"
                :image-size="64"
              />
            </template>
          </el-table>
        </div>

        <div class="pager-wrap">
          <el-pagination
            layout="total, prev, pager, next"
            :total="tableTotal"
            :page-size="tableSize"
            :current-page="tablePage"
            size="small"
            @current-change="(p: number) => { tablePage = p; void loadTables() }"
          />
        </div>
      </el-tab-pane>

      <!-- 2. 字段结构 Tab -->
      <el-tab-pane name="columns">
        <template #label>
          <span class="tab-label-custom">
            <el-icon><Tickets /></el-icon>
            <span>字段结构 (Columns)</span>
            <span v-if="columnTotal > 0" class="count-pill">{{ columnTotal }}</span>
          </span>
        </template>

        <div class="sub-toolbar">
          <div class="filter-left">
            <el-input
              v-model="selectedTable"
              placeholder="按表名过滤字段..."
              clearable
              class="table-search-input"
              :prefix-icon="Search"
              @keyup.enter="() => { columnPage = 1; void loadColumns() }"
              @clear="() => { columnPage = 1; void loadColumns() }"
            />
            <el-button @click="() => { columnPage = 1; void loadColumns() }">查询</el-button>
          </div>

          <div v-if="selectedTable" class="filter-active-pill">
            <span>当前筛选表: <strong>{{ selectedTable }}</strong></span>
            <el-icon class="clear-filter-icon" @click="clearTableFilter"><Close /></el-icon>
          </div>
        </div>

        <el-alert
          v-if="columnsError"
          type="error"
          show-icon
          :closable="false"
          :title="columnsError"
          class="block-gap"
        />

        <div class="table-frame">
          <el-table
            v-loading="columnsLoading"
            :data="columns"
            border
            stripe
            size="small"
            class="custom-table"
          >
            <el-table-column prop="tableName" label="所属数据表" min-width="130" show-overflow-tooltip>
              <template #default="scope">
                <span class="table-name-code">{{ scope.row.tableName }}</span>
              </template>
            </el-table-column>

            <el-table-column prop="columnName" label="字段编码" min-width="130" show-overflow-tooltip>
              <template #default="scope">
                <div class="column-name-cell">
                  <el-icon v-if="scope.row.primaryKey" class="pk-icon"><Key /></el-icon>
                  <span class="column-code" :class="{ 'is-pk': scope.row.primaryKey }">
                    {{ scope.row.columnName }}
                  </span>
                </div>
              </template>
            </el-table-column>

            <el-table-column prop="dataType" label="数据类型" width="120">
              <template #default="scope">
                <span class="datatype-pill">{{ scope.row.dataType }}</span>
              </template>
            </el-table-column>

            <el-table-column prop="columnComment" label="字段业务中文注释" min-width="160" show-overflow-tooltip>
              <template #default="scope">
                <span class="comment-text">{{ scope.row.columnComment || '—' }}</span>
              </template>
            </el-table-column>

            <el-table-column prop="primaryKey" label="主键" width="65" align="center">
              <template #default="scope">
                <el-tag v-if="scope.row.primaryKey" size="small" type="warning" effect="dark">
                  PK
                </el-tag>
                <span v-else class="muted-dash">—</span>
              </template>
            </el-table-column>

            <el-table-column prop="nullable" label="可空" width="65" align="center">
              <template #default="scope">
                <span class="null-flag">{{ scope.row.nullable ? 'YES' : 'NO' }}</span>
              </template>
            </el-table-column>

            <el-table-column label="样例值预览" min-width="160" show-overflow-tooltip>
              <template #default="scope">
                <span class="sample-text">
                  {{ sampleText((scope.row as ColumnMetadataItem).sampleValues) }}
                </span>
              </template>
            </el-table-column>

            <template #empty>
              <el-empty :description="columnsError ? '加载失败' : '暂无字段元数据'" :image-size="64" />
            </template>
          </el-table>
        </div>

        <div class="pager-wrap">
          <el-pagination
            layout="total, prev, pager, next"
            :total="columnTotal"
            :page-size="columnSize"
            :current-page="columnPage"
            size="small"
            @current-change="(p: number) => { columnPage = p; void loadColumns() }"
          />
        </div>
      </el-tab-pane>

      <!-- 3. 表关系 Tab -->
      <el-tab-pane name="relationships">
        <template #label>
          <span class="tab-label-custom">
            <el-icon><Share /></el-icon>
            <span>表拓扑关系 (Relationships)</span>
            <span v-if="relationships.length > 0" class="count-pill">{{ relationships.length }}</span>
          </span>
        </template>

        <el-alert
          v-if="relError"
          type="error"
          show-icon
          :closable="false"
          :title="relError"
          class="block-gap"
        />

        <div class="table-frame">
          <el-table
            v-loading="relLoading"
            :data="relationships"
            border
            stripe
            size="small"
            class="custom-table"
          >
            <el-table-column label="源端字段 (Source)" min-width="180" show-overflow-tooltip>
              <template #default="scope">
                <span class="rel-node source-node">
                  {{ scope.row.sourceTable }}.{{ scope.row.sourceColumn }}
                </span>
              </template>
            </el-table-column>

            <el-table-column label="指向" width="70" align="center">
              <template #default>
                <span class="rel-arrow">➔</span>
              </template>
            </el-table-column>

            <el-table-column label="目标端字段 (Target)" min-width="180" show-overflow-tooltip>
              <template #default="scope">
                <span class="rel-node target-node">
                  {{ scope.row.targetTable }}.{{ scope.row.targetColumn }}
                </span>
              </template>
            </el-table-column>

            <el-table-column prop="relationType" label="关系类型" width="130" align="center">
              <template #default="scope">
                <el-tag size="small" type="info" effect="plain">{{ scope.row.relationType }}</el-tag>
              </template>
            </el-table-column>

            <template #empty>
              <el-empty
                :description="relError ? '加载失败' : '暂无物理外键关系（采集后若库中无外键将为空，属正常）'"
                :image-size="64"
              />
            </template>
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.meta-browser {
  display: flex;
  flex-direction: column;
}

.browser-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.head-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.head-title {
  font-size: 14.5px;
  font-weight: 700;
  color: var(--app-text-primary);
}

.unselected-hint {
  font-size: 12px;
  color: var(--app-text-muted);
}

.empty-state-banner {
  padding: 40px 0;
}

.tab-label-custom {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13.5px;
  font-weight: 600;
}

.count-pill {
  font-size: 10.5px;
  font-family: var(--app-font-mono);
  padding: 1px 6px;
  border-radius: 9999px;
  background: rgba(56, 189, 248, 0.12);
  color: var(--app-primary);
  border: 1px solid rgba(56, 189, 248, 0.25);
}

.sub-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.filter-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.table-search-input {
  width: 220px;
}

.filter-active-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--app-primary);
  background: rgba(56, 189, 248, 0.08);
  border: 1px solid rgba(56, 189, 248, 0.25);
  padding: 3px 10px;
  border-radius: 6px;
}

.clear-filter-icon {
  font-size: 13px;
  cursor: pointer;
}

.clear-filter-icon:hover {
  color: var(--app-accent-rose);
}

.table-frame {
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--app-border);
}

.table-name-code {
  font-family: var(--app-font-mono);
  font-size: 12px;
  color: #38bdf8;
  font-weight: 600;
}

.comment-text {
  font-size: 12px;
  color: var(--app-text-secondary);
}

.row-num {
  font-family: var(--app-font-mono);
  font-size: 12px;
  color: var(--app-text-muted);
}

.op-arrow {
  margin-left: 2px;
  font-size: 11px;
}

.column-name-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.pk-icon {
  color: #fbbf24;
  font-size: 13px;
}

.column-code {
  font-family: var(--app-font-mono);
  font-size: 12px;
  color: var(--app-text-primary);
}

.column-code.is-pk {
  color: #fbbf24;
  font-weight: 700;
}

.datatype-pill {
  font-family: var(--app-font-mono);
  font-size: 11px;
  color: #c084fc;
}

.muted-dash {
  color: var(--app-text-muted);
}

.null-flag {
  font-family: var(--app-font-mono);
  font-size: 11px;
  color: var(--app-text-muted);
}

.sample-text {
  font-family: var(--app-font-mono);
  font-size: 11.5px;
  color: #94a3b8;
}

.rel-node {
  font-family: var(--app-font-mono);
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
}

.source-node {
  background: rgba(56, 189, 248, 0.08);
  border: 1px solid rgba(56, 189, 248, 0.2);
  color: #38bdf8;
}

.target-node {
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.2);
  color: #34d399;
}

.rel-arrow {
  color: var(--app-text-muted);
  font-size: 14px;
}

.pager-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.block-gap {
  margin-bottom: 12px;
}
</style>
