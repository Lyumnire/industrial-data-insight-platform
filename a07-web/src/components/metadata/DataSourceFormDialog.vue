<!-- AI-assisted -->
<!-- 数据源注册/编辑对话框 + 连通测试（不落库）。password 只提交不回显（R3）。
     BUG-020：编辑态 password 为空时改调 POST /datasources/{id}/test（服务端用已存密码）；
     新建/改密仍 POST /datasources/test 且 body 带 password。 -->
<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'
import { describeHttpError } from '../../api/http'
import { createDataSource, testConnectionInfo, testDataSource, updateDataSource } from '../../api/metadata'
import {
  DATASOURCE_STATUS_OPTIONS,
  DB_TYPE_OPTIONS,
  type ConnectionTestResult,
  type DataSourceItem,
  type DataSourceRequest,
} from '../../types/metadata'
import { ElMessage } from 'element-plus'

const props = defineProps<{
  visible: boolean
  /** null = 注册 */
  item: DataSourceItem | null
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'saved'): void
}>()

const formRef = ref<FormInstance | null>(null)
const saving = ref(false)
const testingForm = ref(false)
const testResult = ref<ConnectionTestResult | null>(null)

interface DsForm {
  name: string
  dbType: string
  jdbcUrl: string
  username: string
  password: string
  status: string
  description: string
}

const form = reactive<DsForm>({
  name: '',
  dbType: 'mysql',
  jdbcUrl: '',
  username: '',
  password: '',
  status: 'active',
  description: '',
})

const rules: FormRules = {
  name: [{ required: true, message: '请输入数据源名称', trigger: 'blur' }],
  dbType: [{ required: true, message: '请选择数据库类型', trigger: 'change' }],
  jdbcUrl: [{ required: true, message: '请输入 JDBC URL', trigger: 'blur' }],
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
}

/** 编辑已有数据源且未填密码 → 连通测试走 id/test，使用服务端已保存密码 */
const usesSavedPassword = computed(() => Boolean(props.item) && form.password.length === 0)

const testButtonLabel = computed(() => {
  if (usesSavedPassword.value) return '连通测试（使用已保存密码）'
  return '连通测试（不落库）'
})

const testHint = computed(() => {
  if (usesSavedPassword.value) return '密码留空，将使用已保存密码'
  if (!props.item && form.password.length === 0) return '请先填写密码再测试'
  return '将使用表单中填写的密码（不落库）'
})

watch(
  () => props.visible,
  (visible) => {
    if (!visible) return
    testResult.value = null
    saving.value = false
    testingForm.value = false
    const row = props.item
    Object.assign(form, {
      name: row?.name ?? '',
      dbType: row?.dbType || 'mysql',
      jdbcUrl: row?.jdbcUrl ?? '',
      username: row?.username ?? '',
      password: '',
      status: row?.status || 'active',
      description: row?.description ?? '',
    })
  },
)

function buildRequest(): DataSourceRequest {
  const body: DataSourceRequest = {
    name: form.name.trim(),
    dbType: form.dbType,
    jdbcUrl: form.jdbcUrl.trim(),
    username: form.username.trim(),
    status: form.status,
    description: form.description.trim(),
  }
  if (form.password.length > 0) body.password = form.password
  return body
}

async function handleSave(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  if (!props.item && form.password.length === 0) {
    ElMessage.warning('注册数据源需要填写密码')
    return
  }
  saving.value = true
  try {
    const body = buildRequest()
    if (props.item) {
      await updateDataSource(props.item.id, body)
      ElMessage.success('数据源已更新')
    } else {
      await createDataSource(body)
      ElMessage.success('数据源已注册')
    }
    form.password = ''
    emit('update:visible', false)
    emit('saved')
  } catch (err) {
    ElMessage.error(describeHttpError(err))
  } finally {
    saving.value = false
  }
}

async function handleTestForm(): Promise<void> {
  // 新建且未填密码：直接提示，避免后端 Access denied (using password: NO)
  if (!props.item && form.password.length === 0) {
    testResult.value = { connected: false, message: '注册数据源请先填写密码', tableCount: null }
    return
  }
  testingForm.value = true
  testResult.value = null
  try {
    if (usesSavedPassword.value && props.item) {
      // BUG-020：编辑态密码留空 → 服务端解密 password_enc 后测试
      testResult.value = await testDataSource(props.item.id)
    } else {
      const body: DataSourceRequest = { ...buildRequest(), password: form.password }
      testResult.value = await testConnectionInfo(body)
    }
  } catch (err) {
    testResult.value = { connected: false, message: describeHttpError(err), tableCount: null }
  } finally {
    testingForm.value = false
  }
}

function close(): void {
  emit('update:visible', false)
}
</script>

<template>
  <el-dialog
    :model-value="props.visible"
    :title="props.item ? '编辑数据源' : '注册数据源'"
    width="560px"
    destroy-on-close
    @update:model-value="close"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
      <el-form-item label="名称" prop="name">
        <el-input v-model="form.name" placeholder="如 mes_demo" />
      </el-form-item>
      <el-form-item label="数据库类型" prop="dbType">
        <el-select v-model="form.dbType">
          <el-option v-for="opt in DB_TYPE_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="JDBC URL" prop="jdbcUrl">
        <el-input v-model="form.jdbcUrl" placeholder="jdbc:mysql://host:3306/db?useSSL=false" />
      </el-form-item>
      <el-form-item label="用户名" prop="username">
        <el-input v-model="form.username" autocomplete="off" />
      </el-form-item>
      <el-form-item :label="props.item ? '密码（留空则不修改）' : '密码'">
        <el-input
          v-model="form.password"
          type="password"
          show-password
          autocomplete="new-password"
          placeholder="仅提交，不回显"
        />
        <div class="password-hint">{{ testHint }}</div>
      </el-form-item>
      <el-form-item label="状态">
        <el-select v-model="form.status">
          <el-option v-for="s in DATASOURCE_STATUS_OPTIONS" :key="s" :label="s" :value="s" />
        </el-select>
      </el-form-item>
      <el-form-item label="描述">
        <el-input v-model="form.description" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>

    <div class="test-row">
      <el-button :loading="testingForm" @click="handleTestForm">{{ testButtonLabel }}</el-button>
      <el-tag v-if="testResult" :type="testResult.connected ? 'success' : 'danger'" effect="plain">
        {{ testResult.connected ? '连接成功' : '连接失败' }}
      </el-tag>
      <span v-if="testResult" class="test-msg">
        {{ testResult.message }}
        <template v-if="testResult.tableCount != null"> · 表数 {{ testResult.tableCount }}</template>
      </span>
    </div>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="saving" @click="handleSave">
        {{ props.item ? '保存' : '注册' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.password-hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  line-height: 1.4;
}
.test-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 4px;
}
.test-msg {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
