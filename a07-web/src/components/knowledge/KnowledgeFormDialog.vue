<!-- AI-assisted -->
<!-- 知识实体新建/编辑表单对话框：字段随 resource 切换；数组字段以逗号分隔提交（契约 List<String>）。 -->
<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import {
  DOMAIN_OPTIONS,
  RESOURCE_LABELS,
  STATUS_OPTIONS,
  type KnowledgeItem,
  type KnowledgeRequest,
  type KnowledgeResource,
} from '../../types/knowledge'
import { joinCsv, splitCsv } from '../../api/common'

const props = defineProps<{
  resource: KnowledgeResource
  visible: boolean
  /** null = 新建 */
  item: KnowledgeItem | null
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'submit', body: KnowledgeRequest, editingId: number | null): void
}>()

const formRef = ref<FormInstance | null>(null)

interface FormState {
  code: string
  name: string
  description: string
  domain: string
  status: string
  formulaSql: string
  unit: string
  sourceTables: string
  sourceColumns: string
  ruleType: string
  content: string
  appliesTo: string
  relatedObjectIds: string
  relatedMetricIds: string
}

function emptyForm(): FormState {
  return {
    code: '',
    name: '',
    description: '',
    domain: '',
    status: 'active',
    formulaSql: '',
    unit: '',
    sourceTables: '',
    sourceColumns: '',
    ruleType: '',
    content: '',
    appliesTo: '',
    relatedObjectIds: '',
    relatedMetricIds: '',
  }
}

const form = reactive<FormState>(emptyForm())
const submitting = ref(false)

const isEdit = computed(() => props.item != null)
const title = computed(
  () => `${isEdit.value ? '编辑' : '新建'}${RESOURCE_LABELS[props.resource]}`,
)
const isMetric = computed(() => props.resource === 'metrics')
const isRule = computed(() => props.resource === 'rules')
const isTopic = computed(() => props.resource === 'topics')

watch(
  () => props.visible,
  (visible) => {
    if (!visible) return
    const source = props.item as Record<string, unknown> | null
    const next = emptyForm()
    if (source) {
      next.code = str(source.code)
      next.name = str(source.name)
      next.description = str(source.description)
      next.domain = str(source.domain)
      next.status = str(source.status) || 'active'
      next.formulaSql = str(source.formulaSql)
      next.unit = str(source.unit)
      next.sourceTables = joinCsv(source.sourceTables as string[] | null)
      next.sourceColumns = joinCsv(source.sourceColumns as string[] | null)
      next.ruleType = str(source.ruleType)
      next.content = str(source.content)
      next.appliesTo = joinCsv(source.appliesTo as string[] | null)
      next.relatedObjectIds = joinCsv(source.relatedObjectIds as string[] | null)
      next.relatedMetricIds = joinCsv(source.relatedMetricIds as string[] | null)
    }
    Object.assign(form, next)
    submitting.value = false
  },
)

function str(value: unknown): string {
  return typeof value === 'string' ? value : value == null ? '' : String(value)
}

const rules: FormRules = {
  code: [{ required: true, message: '请输入编码 code', trigger: 'blur' }],
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  ruleType: [{ required: true, message: '规则类型必填', trigger: 'blur' }],
  content: [{ required: true, message: '规则内容必填', trigger: 'blur' }],
}

function buildBody(): KnowledgeRequest {
  const base = {
    code: form.code.trim(),
    name: form.name.trim(),
    status: form.status.trim() || undefined,
  }
  if (isRule.value) {
    return {
      ...base,
      ruleType: form.ruleType.trim(),
      content: form.content.trim(),
      appliesTo: splitCsv(form.appliesTo),
    }
  }
  const objBody = {
    ...base,
    description: form.description.trim(),
    domain: form.domain.trim(),
  }
  if (isMetric.value) {
    return {
      ...objBody,
      formulaSql: form.formulaSql.trim(),
      unit: form.unit.trim(),
      sourceTables: splitCsv(form.sourceTables),
      sourceColumns: splitCsv(form.sourceColumns),
    }
  }
  if (isTopic.value) {
    return {
      ...objBody,
      relatedObjectIds: splitCsv(form.relatedObjectIds),
      relatedMetricIds: splitCsv(form.relatedMetricIds),
    }
  }
  return objBody
}

async function handleSubmit(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    emit('submit', buildBody(), props.item ? props.item.id : null)
  } finally {
    submitting.value = false
  }
}

function close(): void {
  emit('update:visible', false)
}
</script>

<template>
  <el-dialog
    :model-value="props.visible"
    :title="title"
    width="560px"
    destroy-on-close
    @update:model-value="close"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
      <el-form-item label="编码 code" prop="code">
        <el-input v-model="form.code" placeholder="唯一编码，如 yield_rate" :disabled="isEdit" />
      </el-form-item>
      <el-form-item label="名称" prop="name">
        <el-input v-model="form.name" placeholder="展示名称" />
      </el-form-item>

      <template v-if="!isRule">
        <el-form-item label="业务域" prop="domain">
          <el-select v-model="form.domain" clearable filterable allow-create placeholder="如 生产/质量/设备/库存">
            <el-option v-for="d in DOMAIN_OPTIONS" :key="d" :label="d" :value="d" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="口径说明 / 业务含义" />
        </el-form-item>
      </template>

      <template v-if="isMetric">
        <el-form-item label="公式 SQL">
          <el-input v-model="form.formulaSql" type="textarea" :rows="2" placeholder="如 SUM(qualified_qty)/NULLIF(SUM(produced_qty),0)" />
        </el-form-item>
        <el-form-item label="单位">
          <el-input v-model="form.unit" placeholder="如 % / 件 / 分钟" />
        </el-form-item>
        <el-form-item label="来源表（逗号分隔）">
          <el-input v-model="form.sourceTables" placeholder="process_output, quality_inspections" />
        </el-form-item>
        <el-form-item label="来源字段（逗号分隔）">
          <el-input v-model="form.sourceColumns" placeholder="produced_qty, qualified_qty" />
        </el-form-item>
      </template>

      <template v-if="isRule">
        <el-form-item label="规则类型" prop="ruleType">
          <el-input v-model="form.ruleType" placeholder="如 quality / scheduling" />
        </el-form-item>
        <el-form-item label="规则内容" prop="content">
          <el-input v-model="form.content" type="textarea" :rows="4" placeholder="规则业务描述" />
        </el-form-item>
        <el-form-item label="适用对象（逗号分隔）">
          <el-input v-model="form.appliesTo" placeholder="table:process_output, metric:defect_rate" />
        </el-form-item>
      </template>

      <template v-if="isTopic">
        <el-form-item label="关联对象 ID（逗号分隔）">
          <el-input v-model="form.relatedObjectIds" placeholder="1, 2, 3" />
        </el-form-item>
        <el-form-item label="关联指标 ID（逗号分隔）">
          <el-input v-model="form.relatedMetricIds" placeholder="4, 5" />
        </el-form-item>
      </template>

      <el-form-item label="状态" prop="status">
        <el-select v-model="form.status" filterable allow-create placeholder="active">
          <el-option v-for="s in STATUS_OPTIONS" :key="s" :label="s" :value="s" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="handleSubmit">保存</el-button>
    </template>
  </el-dialog>
</template>
