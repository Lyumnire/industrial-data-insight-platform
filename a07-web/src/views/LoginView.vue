<!-- AI-assisted -->
<!-- 登录页：企业制造数据智能问析平台门户，采用宽阔分屏排版、清晰架构脉络与敏捷角色切换 -->
<script setup lang="ts">
import { reactive, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import BrandLogo from '../components/BrandLogo.vue'
import {
  Lock,
  User,
  Sunny,
  Moon,
} from '@element-plus/icons-vue'

const router = useRouter()
const auth = useAuthStore()

const formRef = ref<FormInstance | null>(null)
const loading = ref(false)
const form = reactive({
  username: 'admin',
  password: 'admin123',
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

const quickAccounts = [
  { role: 'admin', name: '系统管理员', user: 'admin', pass: 'admin123', tag: '演示推荐' },
  { role: 'dm', name: '数据主管', user: 'dm', pass: 'dm123456', tag: '资源与图谱' },
  { role: 'user', name: '业务分析员', user: 'user', pass: 'user123456', tag: '问析检索' },
]

function fillAccount(acc: (typeof quickAccounts)[number]): void {
  form.username = acc.user
  form.password = acc.pass
}

const isDark = ref(true)

onMounted(() => {
  isDark.value = document.documentElement.classList.contains('dark')
})

function toggleTheme(): void {
  isDark.value = !isDark.value
  if (isDark.value) {
    document.documentElement.classList.add('dark')
    localStorage.setItem('a07_theme', 'dark')
  } else {
    document.documentElement.classList.remove('dark')
    localStorage.setItem('a07_theme', 'light')
  }
}

async function handleSubmit(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    const ok = await auth.login({ username: form.username, password: form.password })
    if (ok) {
      await router.replace('/')
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrapper">
    <!-- 背景微网格纹理 -->
    <div class="grid-texture"></div>

    <div class="split-layout">
      <!-- 左侧：平台架构与技术底座展板 -->
      <section class="brand-section">
        <!-- 品牌水印：大尺寸幽灵级 Logo 垫于文案之后（纯视觉锚点，不参与交互，R4 不承载信息） -->
        <div class="login-logo-watermark" aria-hidden="true">
          <BrandLogo :size="600" />
        </div>
        <div class="hero-body">
          <div class="contest-badge">
            <span>企业级数据智能底座</span>
          </div>

          <h1 class="hero-title">
            面向制造全域的<br />
            <span class="title-highlight">受控数据问析平台</span>
          </h1>

          <p class="hero-lead">
            以受控只读沙箱与业务知识网络为纽带，实现自然语言到指标口径定位、受控查询执行与工业算法建模的端到端闭环。
          </p>

          <div class="intro-list">
            <div class="intro-item">
              <div class="intro-title">湖仓资产统一接入</div>
              <p class="intro-desc">制造异构数据源自动采集表字段语义，构建业务对象、指标、规则、主题四维知识网络。</p>
            </div>
            <div class="intro-item">
              <div class="intro-title">受控只读沙箱执行</div>
              <p class="intro-desc">只读连接池隔离防护，多层安全校验拦截未授权与越权操作。</p>
            </div>
            <div class="intro-item">
              <div class="intro-title">工业算法建模洞察</div>
              <p class="intro-desc">内置六大典型算法与流式图表引擎，从数据洞察到决策报告一站输出。</p>
            </div>
          </div>
        </div>

        <div class="brand-footer">
          <div class="telemetry-item">
            <span class="pulse-dot"></span>
            <span class="telemetry-label">数据沙箱</span>
            <span class="telemetry-val">只读守护中</span>
          </div>
          <div class="telemetry-divider"></div>
          <div class="telemetry-item">
            <span class="pulse-dot"></span>
            <span class="telemetry-label">知识网络</span>
            <span class="telemetry-val">拓扑映射在线</span>
          </div>
          <div class="telemetry-divider"></div>
          <div class="telemetry-item">
            <span class="pulse-dot"></span>
            <span class="telemetry-label">执行引擎</span>
            <span class="telemetry-val">流式协同就绪</span>
          </div>
        </div>
      </section>

      <!-- 右侧：认证与登录交互区 -->
      <section class="auth-section">
        <div class="auth-top-bar">
          <el-tooltip :content="isDark ? '切换至浅色模式' : '切换至暗色科技模式'" placement="bottom">
            <button class="theme-toggle-pill" @click="toggleTheme" type="button">
              <el-icon><Sunny v-if="isDark" /><Moon v-else /></el-icon>
              <span>{{ isDark ? '浅色模式' : '暗色模式' }}</span>
            </button>
          </el-tooltip>
        </div>

        <div class="auth-card">
          <div class="card-intro">
            <h2 class="auth-title">系统登录</h2>
            <p class="auth-subtitle">请选择角色一键填充演示，或输入专属账号凭证</p>
          </div>

          <!-- 快速角色选择分段控制器 -->
          <div class="role-switcher-box">
            <div class="switcher-header">
              <span class="switcher-title">快速选择角色登录</span>
              <span class="switcher-tip">评审一键预置</span>
            </div>
            <div class="role-segments">
              <button
                v-for="acc in quickAccounts"
                :key="acc.role"
                type="button"
                class="role-segment-btn"
                :class="{ 'is-active': form.username === acc.user }"
                @click="fillAccount(acc)"
              >
                <span class="segment-name">{{ acc.name }}</span>
                <span class="segment-code">{{ acc.user }}</span>
              </button>
            </div>
          </div>

          <el-alert
            v-if="auth.loginError"
            class="login-alert"
            type="error"
            show-icon
            :closable="false"
            :title="auth.loginError"
          />

          <el-form
            ref="formRef"
            :model="form"
            :rules="rules"
            label-position="top"
            size="large"
            class="login-form"
            @submit.prevent="handleSubmit"
          >
            <el-form-item label="用户名" prop="username">
              <el-input
                v-model="form.username"
                name="username"
                autocomplete="username"
                placeholder="请输入用户名（如 admin）"
                :prefix-icon="User"
              />
            </el-form-item>

            <el-form-item label="密码" prop="password">
              <el-input
                v-model="form.password"
                type="password"
                name="password"
                autocomplete="current-password"
                show-password
                placeholder="请输入密码"
                :prefix-icon="Lock"
                @keyup.enter="handleSubmit"
              />
            </el-form-item>

            <el-button
              class="submit-login-btn"
              type="primary"
              native-type="submit"
              :loading="loading"
            >
              {{ loading ? '身份核验中...' : '进入问析工作台' }}
            </el-button>
          </el-form>

          <div class="auth-footer-tag">
            <el-icon class="footer-icon"><Lock /></el-icon>
            <span>企业级数据安全访问 · 操作合规审计已启用</span>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.login-wrapper {
  position: relative;
  min-height: 100vh;
  width: 100%;
  background: var(--app-bg-deep);
  color: var(--app-text-primary);
  display: flex;
  overflow-x: hidden;
}

.grid-texture {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(var(--app-border) 1px, transparent 1px),
    linear-gradient(90deg, var(--app-border) 1px, transparent 1px);
  background-size: 40px 40px;
  opacity: 0.25;
  pointer-events: none;
}

html:not(.dark) .grid-texture {
  opacity: 0.45;
}

.split-layout {
  position: relative;
  z-index: 1;
  display: flex;
  width: 100%;
  min-height: 100vh;
}

/* ================= 左侧展板 ================= */
.brand-section {
  position: relative;
  overflow: hidden;
  flex: 1.15;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 48px 60px;
  background: var(--app-bg-surface);
  border-right: 1px solid var(--app-border);
}

/* 品牌水印：幽灵级大 Logo，视觉锚点不抢文案（对比度优先，透明度压至 6%） */
.login-logo-watermark {
  position: absolute;
  right: -130px;
  top: 50%;
  transform: translateY(-50%);
  opacity: 0.06;
  z-index: 0;
  pointer-events: none;
  user-select: none;
}

.hero-body,
.brand-footer {
  position: relative;
  z-index: 1;
}

html:not(.dark) .brand-section {
  background: #f8fafc;
  border-right-color: #e2e8f0;
}

html:not(.dark) .brand-logo-wrap {
  background: #ffffff;
  border-color: #e2e8f0;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.hero-body {
  margin: auto 0;
  padding: 36px 0;
  max-width: 580px;
}

.contest-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  font-size: 12px;
  font-weight: 600;
  background: rgba(14, 165, 233, 0.08);
  border: 1px solid rgba(14, 165, 233, 0.25);
  color: var(--app-primary);
  border-radius: 9999px;
  margin-bottom: 22px;
}

html:not(.dark) .contest-badge {
  background: #f0f9ff;
  border-color: #bae6fd;
  color: #0284c7;
}

.hero-title {
  font-size: 34px;
  font-weight: 800;
  line-height: 1.3;
  margin: 0 0 16px;
  color: var(--app-text-primary);
  letter-spacing: -0.5px;
}

.title-highlight {
  color: var(--app-primary);
}

.hero-lead {
  font-size: 14.5px;
  line-height: 1.7;
  color: var(--app-text-secondary);
  margin: 0 0 32px;
}

.intro-list {
  display: flex;
  flex-direction: column;
  gap: 24px;
  margin-top: 6px;
}

.intro-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--app-text-primary);
  margin-bottom: 4px;
}

.intro-desc {
  font-size: 13px;
  line-height: 1.65;
  color: var(--app-text-secondary);
  margin: 0;
  max-width: 46ch;
}

.brand-footer {
  display: flex;
  align-items: center;
  gap: 18px;
  padding-top: 24px;
  border-top: 1px solid var(--app-border);
}

html:not(.dark) .brand-footer {
  border-top-color: #e2e8f0;
}

.pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--app-accent-emerald);
  box-shadow: 0 0 6px rgba(16, 185, 129, 0.6);
}

.telemetry-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.telemetry-label {
  color: var(--app-text-muted);
}

.telemetry-val {
  color: var(--app-text-primary);
  font-weight: 600;
}

.telemetry-divider {
  width: 1px;
  height: 14px;
  background: var(--app-border);
}

/* ================= 右侧登录区 ================= */
.auth-section {
  flex: 0.95;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  position: relative;
  background: var(--app-bg-deep);
}

html:not(.dark) .auth-section {
  background: #ffffff;
}

.auth-top-bar {
  position: absolute;
  top: 32px;
  right: 36px;
  z-index: 10;
}

.theme-toggle-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: var(--app-bg-surface);
  border: 1px solid var(--app-border);
  border-radius: 8px;
  font-size: 12px;
  font-weight: 500;
  color: var(--app-text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
}

html:not(.dark) .theme-toggle-pill {
  background: #f8fafc;
  border-color: #e2e8f0;
  color: #475569;
}

.theme-toggle-pill:hover {
  border-color: var(--app-primary);
  color: var(--app-primary);
}

.auth-card {
  width: 100%;
  max-width: 460px;
  padding: 0;
  background: transparent;
  border: none;
  box-shadow: none;
}

html:not(.dark) .auth-card {
  background: transparent;
  border: none;
  box-shadow: none;
}

.card-intro {
  margin-bottom: 24px;
}

.auth-title {
  font-size: 28px;
  font-weight: 700;
  margin: 0 0 6px;
  color: var(--app-text-primary);
  letter-spacing: -0.3px;
}

.auth-subtitle {
  font-size: 14px;
  color: var(--app-text-secondary);
  margin: 0;
}

/* 分段角色选择器 */
.role-switcher-box {
  margin-bottom: 22px;
  padding: 12px;
  background: var(--app-bg-surface);
  border: 1px solid var(--app-border);
  border-radius: 10px;
}

html:not(.dark) .role-switcher-box {
  background: #f8fafc;
  border-color: #e2e8f0;
}

.switcher-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.switcher-title {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--app-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.switcher-tip {
  font-size: 10.5px;
  color: var(--app-primary);
  font-weight: 500;
}

.role-segments {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
}

.role-segment-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 8px 4px;
  background: var(--app-bg-deep);
  border: 1px solid var(--app-border);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.18s ease;
}

html:not(.dark) .role-segment-btn {
  background: #ffffff;
  border-color: #e2e8f0;
}

.role-segment-btn:hover {
  border-color: var(--app-primary);
}

.role-segment-btn.is-active {
  background: rgba(14, 165, 233, 0.1);
  border-color: var(--app-primary);
  box-shadow: 0 0 0 1px var(--app-primary);
}

html:not(.dark) .role-segment-btn.is-active {
  background: #f0f9ff;
  border-color: #0284c7;
  box-shadow: 0 0 0 1px #0284c7;
}

.segment-name {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--app-text-primary);
}

.role-segment-btn.is-active .segment-name {
  color: var(--app-primary);
}

.segment-code {
  font-family: var(--app-font-mono);
  font-size: 10px;
  color: var(--app-text-muted);
}

.role-segment-btn.is-active .segment-code {
  color: var(--app-primary);
  font-weight: 600;
}

.login-alert {
  margin-bottom: 18px;
}

.login-form :deep(.el-form-item) {
  margin-bottom: 18px;
}

.login-form :deep(.el-form-item__label) {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--app-text-regular);
  padding-bottom: 6px;
}

.submit-login-btn {
  width: 100%;
  height: 46px;
  font-size: 14.5px;
  font-weight: 600;
  background: var(--app-gradient-primary) !important;
  border: 1px solid rgba(255, 255, 255, 0.18) !important;
  color: #ffffff !important;
  border-radius: 10px;
  margin-top: 10px;
  box-shadow: 0 4px 14px rgba(14, 165, 233, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.25);
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.submit-login-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 20px rgba(14, 165, 233, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.35);
}

.submit-login-btn:active {
  transform: translateY(0);
}

.auth-footer-tag {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-top: 24px;
  font-size: 12px;
  color: var(--app-text-muted);
}

.footer-icon {
  font-size: 13px;
  color: var(--app-text-muted);
}

/* ================= 响应式适配 ================= */
@media (max-width: 1024px) {
  .split-layout {
    flex-direction: column;
  }

  .brand-section {
    padding: 36px 24px;
    border-right: none;
    border-bottom: 1px solid var(--app-border);
  }

  .hero-body {
    padding: 20px 0;
  }

  .brand-footer {
    display: none;
  }

  .auth-section {
    padding: 40px 20px;
  }

  .auth-top-bar {
    position: static;
    margin-bottom: 20px;
    align-self: flex-end;
  }
}
</style>
