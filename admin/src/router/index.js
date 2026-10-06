/** 管理端路由配置：所有页面组件都使用可被 Vite 静态分析的显式导入。 */
import { createRouter, createWebHistory } from 'vue-router'

/**
 * 页面组件映射。键名与 menuRoutes 中的 routeKey 一一对应，避免通过路径
 * 字符串猜测 Vue 文件名导致生产构建遗漏页面模块。
 */
export const viewComponents = {
  login: () => import('@/views/Login.vue'),
  dashboard: () => import('@/views/Dashboard.vue'),
  knowledgeGraph: () => import('@/views/KnowledgeGraph.vue'),
  questions: () => import('@/views/Questions.vue'),
  students: () => import('@/views/Students.vue'),
  social: () => import('@/views/Social.vue'),
  aiReports: () => import('@/views/AiReports.vue'),
  config: () => import('@/views/Config.vue'),
}

/** 路由名称与菜单标题映射，供侧边栏复用 */
export const menuRoutes = [
  { path: '/dashboard',       routeKey: 'dashboard',       title: '仪表盘',   icon: 'Odometer' },
  { path: '/knowledge-graph', routeKey: 'knowledgeGraph',  title: '知识图谱', icon: 'Share' },
  { path: '/questions',       routeKey: 'questions',       title: '题库管理', icon: 'Edit' },
  { path: '/students',        routeKey: 'students',        title: '学生数据', icon: 'User' },
  { path: '/social',          routeKey: 'social',          title: '社交管理', icon: 'ChatDotRound' },
  { path: '/ai-reports',      routeKey: 'aiReports',       title: 'AI报告',   icon: 'Document' },
  { path: '/config',          routeKey: 'config',          title: '系统配置', icon: 'Setting' },
]

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: viewComponents.login,
    meta: { title: '登录' },
  },
  {
    path: '/',
    redirect: '/dashboard',
  },
  // 所有管理页面共用 MainLayout
  ...menuRoutes.map((m) => ({
    path: m.path,
    name: m.path.replace('/', '').replace(/-/g, '_'),
    component: viewComponents[m.routeKey],
    meta: { title: m.title, requiresAuth: true },
  })),
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// ---------- 路由守卫 ----------
import { useAdminStore } from '@/stores/admin'

router.beforeEach(async (to, _from, next) => {
  const store = useAdminStore()

  if (to.path === '/login' && store.isLoggedIn) {
    return next('/dashboard')
  }

  if (!to.meta.requiresAuth) return next()

  // 有 token 但无 admin 信息时先尝试恢复；失败时保留 request 层的用户提示，
  // 同时把当前导航安全地送回登录页。
  if (store.token && !store.admin) {
    try {
      await store.fetchAdminInfo()
    } catch (error) {
      if (!error) return next('/login')
      return next({ path: '/login', query: { redirect: to.fullPath } })
    }
  }

  if (!store.isLoggedIn) {
    return next({ path: '/login', query: { redirect: to.fullPath } })
  }
  next()
})

export default router
