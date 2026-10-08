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
  let sessionVersion = 0
  let sessionChangeReason = 'initial'
  let sessionChangeFromVersion = -1

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

  function isCurrentSession(version, expectedToken) {
    return version === sessionVersion && token.value === expectedToken
  }

  function getSessionSnapshot() {
    return { version: sessionVersion, token: token.value }
  }

  function isSessionSnapshotCurrent(snapshot) {
    return Boolean(snapshot) && isCurrentSession(snapshot.version, snapshot.token)
  }

  // A current session may be invalidated by its own auth failure. That failure
  // still owns the normal login redirect; a superseded session does not.
  function isSessionSnapshotCurrentOrAuthFailure(snapshot) {
    return isSessionSnapshotCurrent(snapshot)
      || (Boolean(snapshot)
        && sessionChangeFromVersion === snapshot.version
        && sessionChangeReason === 'auth-failure')
  }

  function beginSessionChange(reason = 'change') {
    sessionChangeFromVersion = sessionVersion
    sessionChangeReason = reason
    sessionVersion += 1
    initializationPromise = null
    sessionError.value = ''
    return sessionVersion
  }

  /** 清理本地登录态。后端无状态退出接口，因此退出只需清除本地凭证。 */
  function logout(reason = 'logout') {
    beginSessionChange(reason)
    token.value = ''
    userInfo.value = { ...EMPTY_USER }
    uni.removeStorageSync('auth_token')
  }

  /** 拉取并校验当前学生身份。 */
  async function fetchCurrentUser(expectedVersion = sessionVersion, expectedToken = token.value) {
    const { get } = await import('@/utils/request')
    if (!isCurrentSession(expectedVersion, expectedToken)) return null
    const currentUser = await get('/auth/me')
    if (!isCurrentSession(expectedVersion, expectedToken)) return null

    if (currentUser?.role !== 'student') {
      const error = new Error('当前账号不是学生账号，无法进入学生端')
      error.code = 40101
      error.status = 403
      logout('auth-failure')
      throw error
    }
    setUserInfo(currentUser)
    return currentUser
  }

  /**
   * 应用启动时恢复并校验会话。
   * 网络异常不会伪造已登录状态；下一次进入页面时仍可重新触发校验。
   */
  function initializeSession() {
    if (initializationPromise) return initializationPromise

    const versionAtStart = sessionVersion
    let tokenAtStart = ''
    const run = async () => {
      try {
        sessionError.value = ''
        restoreToken()
        tokenAtStart = token.value
        if (!tokenAtStart) return false

        const currentUser = await fetchCurrentUser(versionAtStart, tokenAtStart)
        if (currentUser && isCurrentSession(versionAtStart, tokenAtStart)) {
          sessionChangeReason = 'authenticated'
        }
        return Boolean(currentUser && isCurrentSession(versionAtStart, tokenAtStart))
      } catch (error) {
        // 旧账号的请求不能覆盖新账号的错误或登录态。
        if (!isCurrentSession(versionAtStart, tokenAtStart)) return false

        sessionError.value = error?.message || '登录状态校验失败'
        if (error?.status === 401 || error?.code === 40100 || error?.code === 40101) {
          logout('auth-failure')
        }
        return false
      } finally {
        // A superseded initialization must not mark a newer session ready.
        if (isCurrentSession(versionAtStart, tokenAtStart)) authReady.value = true
      }
    }

    // 先拿到 Promise，再挂清理回调。这样无 Token 分支即使同步完成，
    // 也不会在外层赋值之后把已完成的 false Promise 残留在缓存里。
    const promise = run()
    initializationPromise = promise
    const clearInitialization = () => {
      if (initializationPromise === promise) initializationPromise = null
    }
    promise.then(clearInitialization, clearInitialization)

    return promise
  }

  /** 登录并立即校验角色。 */
  async function login(username, password) {
    // Invalidate older login POSTs before any await. Otherwise an older
    // response can become the newest session when it arrives late.
    const loginTokenAtStart = token.value
    const loginVersion = beginSessionChange('login')
    const { post } = await import('@/utils/request')
    if (!isCurrentSession(loginVersion, loginTokenAtStart)) {
      throw createStaleSessionError()
    }
    const result = await post('/auth/login', { username, password })
    if (!isCurrentSession(loginVersion, loginTokenAtStart)) {
      throw createStaleSessionError()
    }
    setToken(result?.token)
    const loginToken = token.value
    try {
      const currentUser = await fetchCurrentUser(loginVersion, loginToken)
      if (!currentUser) {
        throw createStaleSessionError()
      }
      authReady.value = true
      sessionError.value = ''
      sessionChangeReason = 'authenticated'
      return result
    } catch (error) {
      if (isCurrentSession(loginVersion, loginToken)) logout()
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
    const guardSession = getSessionSnapshot()
    const valid = await initializeSession()
    if (valid) return true

    // A guard is allowed to navigate only when its failed initialization still
    // belongs to the current session, or when this exact session was invalidated
    // by its own authentication failure (for example expired/admin /auth/me).
    // A late A result after B login/exit must remain a false result without
    // touching B's navigation.
    const guardOwnsFailure = isSessionSnapshotCurrentOrAuthFailure(guardSession)
    if (redirect && guardOwnsFailure) {
      const pages = typeof getCurrentPages === 'function' ? getCurrentPages() : []
      const current = pages[pages.length - 1]
      const isAuthPage = current?.route === 'pages/auth/login' || current?.route === 'pages/auth/register'
      if (!isAuthPage) uni.reLaunch({ url: LOGIN_PAGE })
    }
    return false
  }

  function createStaleSessionError() {
    const error = new Error('登录状态已更新，请重试')
    error.code = 'SESSION_STALE'
    error.requestSuppressed = true
    return error
  }

  return {
    userInfo,
    token,
    authReady,
    sessionError,
    isLoggedIn,
    getSessionSnapshot,
    isSessionSnapshotCurrent,
    isSessionSnapshotCurrentOrAuthFailure,
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
