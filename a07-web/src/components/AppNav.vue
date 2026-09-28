<!-- AI-assisted -->
<!-- 应用内顶栏导航：全站统一顶栏，四模块路由导航、主题切换与用户身份。 -->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import BrandLogo from './BrandLogo.vue'
import {
  ChatDotRound,
  Collection,
  Coin,
  Cpu,
  Moon,
  Sunny,
  SwitchButton,
  UserFilled,
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

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

const links = [
  { to: '/', label: '问析工作台', name: 'workbench', icon: ChatDotRound },
  { to: '/knowledge', label: '业务知识中心', name: 'knowledge', icon: Collection },
  { to: '/metadata', label: '数据资源中心', name: 'metadata', icon: Coin },
  { to: '/ml', label: '建模工作台', name: 'ml', icon: Cpu },
] as const

function isActive(name: string): boolean {
  if (name === 'knowledge') {
    return route.name === 'knowledge' || route.name === 'knowledge-graph'
  }
  return route.name === name
}

function logout(): void {
  auth.logout()
  void router.replace('/login')
}

const roleBadgeType = computed(() => {
  if (auth.role === 'admin') return 'danger'
  if (auth.role === 'dm') return 'warning'
  return 'success'
})

const roleDisplayName = computed(() => {
  if (auth.role === 'admin') return '管理员'
  if (auth.role === 'dm') return '数据管理员'
  if (auth.role === 'user') return '业务分析员'
  return auth.role || '访客'
})
</script>

<template>
  <header class="app-nav">
    <div class="nav-left">
      <router-link to="/" class="brand-link">
        <div class="brand-logo">
          <BrandLogo :size="26" />
        </div>
        <div class="brand-meta">
          <span class="brand-title">制造数据智能问析平台</span>
        </div>
      </router-link>
    </div>

    <nav class="nav-tabs">
      <router-link
        v-for="link in links"
        :key="link.name"
        :to="link.to"
        class="nav-tab-item"
        :class="{ 'is-active': isActive(link.name) }"
      >
        <el-icon class="tab-icon"><component :is="link.icon" /></el-icon>
        <span class="tab-label">{{ link.label }}</span>
      </router-link>
    </nav>

    <div class="nav-right">
      <el-tooltip :content="isDark ? '切换至浅色模式' : '切换至暗色科技模式'" placement="bottom">
        <button class="theme-toggle-btn" @click="toggleTheme">
          <el-icon><Sunny v-if="isDark" /><Moon v-else /></el-icon>
        </button>
      </el-tooltip>

      <div class="user-pill" v-if="auth.role">
        <el-avatar :size="24" class="user-avatar">
          <el-icon><UserFilled /></el-icon>
        </el-avatar>
        <div class="user-info">
          <span class="user-name">{{ auth.role }}</span>
          <el-tag :type="roleBadgeType" size="small" effect="dark" class="role-tag">
            {{ roleDisplayName }}
          </el-tag>
        </div>
      </div>

      <el-button text class="logout-btn" @click="logout">
        <el-icon><SwitchButton /></el-icon>
        <span>退出</span>
      </el-button>
    </div>
  </header>
</template>

<style scoped>
.app-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px;
  padding: 0 24px;
  background: var(--app-bg-surface);
  border-bottom: 1px solid var(--app-border);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.15);
  position: sticky;
  top: 0;
  z-index: 100;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  flex-shrink: 0;
}

.nav-left {
  display: flex;
  align-items: center;
}

.brand-link {
  display: flex;
  align-items: center;
  gap: 10px;
  text-decoration: none;
}

.brand-logo {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  background: linear-gradient(135deg, rgba(56, 189, 248, 0.15) 0%, rgba(99, 102, 241, 0.1) 100%);
  border: 1px solid rgba(56, 189, 248, 0.35);
  border-radius: 8px;
}

.brand-meta {
  display: flex;
  align-items: center;
}

.brand-title {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.3px;
  color: var(--app-text-primary);
}

.nav-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  background: var(--app-bg-deep);
  padding: 3px;
  border-radius: 8px;
  border: 1px solid var(--app-border);
}

.nav-tab-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 6px;
  text-decoration: none;
  font-size: 13.5px;
  font-weight: 500;
  color: var(--app-text-secondary);
  transition: all 0.18s ease;
}

.tab-icon {
  font-size: 14px;
}

.nav-tab-item:hover:not(.is-active) {
  color: var(--app-text-primary);
  background: rgba(255, 255, 255, 0.08);
}

html:not(.dark) .nav-tab-item:hover:not(.is-active) {
  background: rgba(15, 23, 42, 0.06);
  color: var(--app-text-primary);
}

.nav-tab-item.is-active {
  color: #ffffff !important;
  background: var(--app-primary) !important;
  box-shadow: 0 2px 6px rgba(2, 132, 199, 0.25);
  font-weight: 600;
}

.nav-tab-item.is-active:hover {
  color: #ffffff !important;
  background: var(--app-primary-hover) !important;
}

.nav-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.theme-toggle-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: var(--app-bg-deep);
  border: 1px solid var(--app-border);
  border-radius: 8px;
  color: var(--app-text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
}

.theme-toggle-btn:hover {
  color: var(--app-primary);
  border-color: var(--app-primary);
}

.user-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 10px 3px 5px;
  background: var(--app-bg-deep);
  border: 1px solid var(--app-border);
  border-radius: 9999px;
}

.user-avatar {
  background: var(--app-primary);
  color: #ffffff;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 6px;
}

.user-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--app-text-primary);
}

.role-tag {
  font-size: 10px;
  padding: 0 6px;
  height: 18px;
  line-height: 16px;
  border-radius: 4px;
}

.logout-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--app-text-muted);
  font-size: 12.5px;
  transition: all 0.2s ease;
}

.logout-btn:hover {
  color: var(--app-accent-rose);
}
</style>
