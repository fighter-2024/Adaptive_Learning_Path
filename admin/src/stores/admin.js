/**
 * 管理员状态管理 — Pinia store
 *
 * 对接后端认证接口（docs/API契约文档.md 3.1）：
 * - POST /auth/login  → data: {token, token_type, expires_in}
 * - GET  /auth/me     → data: UserInfo（user_id/username/name/role/...）
 * 注意：/auth/* 不带 /api 前缀（dev 下 Vite 已为 /auth 与 /api 配置代理）。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import request from '@/utils/request'

export const useAdminStore = defineStore('admin', () => {
  // ---- state ----
  const admin = ref(null)
  const token = ref(localStorage.getItem('admin_token') || '')

  // ---- getters ----
  const isLoggedIn = computed(() => !!token.value && admin.value?.role === 'admin')
  const adminName = computed(() => admin.value?.name || '管理员')

  // ---- actions ----
  /** 登录：换取 JWT 并立即拉取管理员信息 */
  async function login(username, password) {
    const res = await request.post('/auth/login', { username, password })
    token.value = res.token
    localStorage.setItem('admin_token', res.token)
    try {
      // 后端登录响应不含用户信息，需再调 /auth/me 获取并校验角色
      await fetchAdminInfo()
    } catch (error) {
      logout()
      throw error
    }
  }

  /** 退出登录 */
  function logout() {
    token.value = ''
    admin.value = null
    localStorage.removeItem('admin_token')
  }

  /** 从 token 恢复管理员信息（用于页面刷新后） */
  async function fetchAdminInfo() {
    if (!token.value) return
    const res = await request.get('/auth/me')
    if (res?.role !== 'admin') {
      logout()
      const error = new Error('当前账号不是管理员账号')
      error.code = 40101
      error.status = 403
      throw error
    }
    admin.value = res
    return res
  }

  return { admin, token, isLoggedIn, adminName, login, logout, fetchAdminInfo }
})
