// AI-assisted
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './style.css'
import App from './App.vue'
import router from './router'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

const app = createApp(App)
const pinia = createPinia()

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(pinia).use(router).use(ElementPlus).mount('#app')

// 仅开发环境：暴露 pinia 供控制台做渲染链路自检（生产构建被死代码消除）
if (import.meta.env.DEV) {
  ;(window as unknown as Record<string, unknown>).__pinia = pinia
}
