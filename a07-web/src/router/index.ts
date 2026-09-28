// AI-assisted
/** 路由：/login 登录页（公开），/ 智能问析工作台（需登录），守卫重定向。 */
import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      name: 'workbench',
      component: () => import('../views/WorkbenchView.vue'),
    },
    {
      // 建模工作台（P2a Task 14.4）
      path: '/ml',
      name: 'ml',
      component: () => import('../views/MlTasksView.vue'),
    },
    {
      // F2 业务知识中心（T-020）
      path: '/knowledge',
      name: 'knowledge',
      component: () => import('../views/KnowledgeView.vue'),
    },
    {
      // F2 知识图谱（T-020）
      path: '/knowledge/graph',
      name: 'knowledge-graph',
      component: () => import('../views/KnowledgeGraphView.vue'),
    },
    {
      // F3 数据资源中心（T-020）
      path: '/metadata',
      name: 'metadata',
      component: () => import('../views/MetadataView.vue'),
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  // BUG-013：token 过期后 isLoggedIn 已判 false；此处区分"过期"与"未登录"，前者给出明白话
  if (to.meta.public !== true && !auth.isLoggedIn) {
    if (auth.token.length > 0) {
      auth.logout()
      auth.loginError = '登录已过期，请重新登录'
    }
    return { name: 'login' }
  }
  if (to.name === 'login' && auth.isLoggedIn) {
    return { name: 'workbench' }
  }
  return true
})

export default router
