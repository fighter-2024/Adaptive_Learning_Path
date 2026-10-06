/**
 * 学生身份状态管理。
 *
 * Token 只负责持久化访问凭证，用户信息必须通过 /auth/me 校验后才能作为
 * 已登录状态使用。这样可以避免过期 Token 或管理员 Token 被学生端误当作
 * 学生身份。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

const EMPTY_USER = {
  userId: '',
  username: '',
  name: '',
  avatar: '',
  role: 'student'
}

const LOGIN_PAGE = '/pages/auth/login'

function toUserInfo(info = {}) {
  return {
    userId: info.user_id || info.userId || '',
    username: info.username || '',
    name: info.name || '',
    avatar: info.avatar || '',
    role: info.role || ''
  }
}

export const useUserStore = defineStore('user', () => {
  const userInfo = ref({ ...EMPTY_USER })
  const token = ref('')
  const authReady = ref(false)
  const sessionError = ref('')
  let initializationPromise = null

  const isLoggedIn = computed(() => Boolean(token.value && userInfo.value.userId))

  /** 保存并更新访问 Token。 */
  function setToken(value) {
    token.value = value || ''
    if (token.value) {
      uni.setStorageSync('auth_token', token.value)
    } else {
      uni.removeStorageSync('auth_token')
    }
  }

  /** 设置 /auth/me 返回的学生信息。 */
  function setUserInfo(info) {
    userInfo.value = toUserInfo(info)
  }

  /** 从本地存储恢复 Token；真正生效前仍需 /auth/me 校验。 */
  function restoreToken() {
    const saved = uni.getStorageSync('auth_token')
    if (saved) {
      token.value = String(saved)
      return true
    }
    return false
  }

  /** 清理本地登录态。后端无状态退出接口，因此退出只需清除本地凭证。 */
  function logout() {
    token.value = ''
    userInfo.value = { ...EMPTY_USER }
    sessionError.value = ''
    uni.removeStorageSync('auth_token')
  }

  /** 拉取并校验当前学生身份。 */
  async function fetchCurrentUser() {
    const { get } = await import('@/utils/request')
    const currentUser = await get('/auth/me')
    if (currentUser?.role !== 'student') {
      const error = new Error('当前账号不是学生账号，无法进入学生端')
      error.code = 40101
      error.status = 403
      logout()
      throw error
    }
    setUserInfo(currentUser)
    return currentUser
  }

  /**
   * 应用启动时恢复并校验会话。
   * 网络异常不会伪造已登录状态；下一次进入页面时仍可重新触发校验。
   */
  async function initializeSession() {
    if (initializationPromise) return initializationPromise

    initializationPromise = (async () => {
      try {
        sessionError.value = ''
        restoreToken()
        if (!token.value) return false

        await fetchCurrentUser()
        return true
      } catch (error) {
        sessionError.value = error?.message || '登录状态校验失败'
        if (error?.status === 401 || error?.code === 40100 || error?.code === 40101) {
          logout()
        }
        return false
      } finally {
        authReady.value = true
        initializationPromise = null
      }
    })()

    return initializationPromise
  }

  /** 登录并立即校验角色。 */
  async function login(username, password) {
    const { post } = await import('@/utils/request')
    const result = await post('/auth/login', { username, password })
    setToken(result?.token)
    try {
      await fetchCurrentUser()
      authReady.value = true
      sessionError.value = ''
      return result
    } catch (error) {
      logout()
      throw error
    }
  }

  /** 注册学生账号；注册接口不自动登录，成功后回到登录页。 */
  async function register(payload) {
    const { post } = await import('@/utils/request')
    return post('/auth/register', { ...payload, role: 'student' })
  }

  /**
   * 页面导航前的学生端守卫。
   * @param {boolean} redirect 是否在未登录时跳转登录页
   */
  async function ensureAuthenticated(redirect = true) {
    const valid = await initializeSession()
    if (valid) return true

    if (redirect) {
      const pages = typeof getCurrentPages === 'function' ? getCurrentPages() : []
      const current = pages[pages.length - 1]
      const isAuthPage = current?.route === 'pages/auth/login' || current?.route === 'pages/auth/register'
      if (!isAuthPage) uni.reLaunch({ url: LOGIN_PAGE })
    }
    return false
  }

  return {
    userInfo,
    token,
    authReady,
    sessionError,
    isLoggedIn,
    setToken,
    setUserInfo,
    restoreToken,
    initializeSession,
    fetchCurrentUser,
    ensureAuthenticated,
    login,
    register,
    logout
  }
})
