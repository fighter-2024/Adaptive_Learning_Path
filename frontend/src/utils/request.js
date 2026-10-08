/**
 * UniApp 网络请求统一封装。
 *
 * 所有学生端接口都经过这里：读取 Pinia Token、解析统一响应、处理
 * 认证失效和网络错误。API 地址只从 Vite 构建环境读取，空值表示使用
 * 当前站点地址（适合由网关或开发服务器代理 /api 和 /auth）。
 */
import { useUserStore } from '@/store/user'

/** 后端 API 基础地址，由 VITE_API_BASE_URL 配置。 */
const BASE_URL = String(import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

/** 请求超时时间（毫秒）。 */
const TIMEOUT = 30000

/** 分页默认每页条数。 */
const DEFAULT_PAGE_SIZE = 20

const LOGIN_PAGE = '/pages/auth/login'

function isAuthPage() {
  const pages = typeof getCurrentPages === 'function' ? getCurrentPages() : []
  const current = pages[pages.length - 1]
  return current?.route === LOGIN_PAGE.slice(1) || current?.route === 'pages/auth/register'
}

function getUserStore() {
  try {
    return useUserStore()
  } catch {
    return null
  }
}

function captureRequestSession(requestToken) {
  const userStore = getUserStore()
  return {
    userStore,
    snapshot: userStore?.getSessionSnapshot?.() || null,
    token: String(requestToken || '')
  }
}

function isCurrentRequestSession(requestSession) {
  if (!requestSession) return true
  const userStore = getUserStore()
  if (requestSession.snapshot) {
    return userStore?.isSessionSnapshotCurrent?.(requestSession.snapshot) ?? false
  }

  // Requests issued before Pinia is active still get a token-based guard;
  // this prevents their late auth failure from clearing a newly persisted token.
  const currentToken = userStore?.token || (() => {
    try {
      return uni.getStorageSync('auth_token') || ''
    } catch {
      return ''
    }
  })()
  return String(currentToken || '') === requestSession.token
}

/**
 * 从 Pinia 读取 Token。应用刚启动且 Pinia 尚未激活时，回退读取本地存储，
 * 避免首个请求因为 store 尚未完成初始化而丢失认证头。
 */
function getToken() {
  const userStore = getUserStore()
  if (userStore?.token) return userStore.token

  try {
    return uni.getStorageSync('auth_token') || ''
  } catch (error) {
    const storageError = new Error('无法读取本地登录状态')
    storageError.cause = error
    return ''
  }
}

function createRequestError(message, options = {}) {
  const error = new Error(message || '请求失败，请稍后重试')
  Object.assign(error, options)
  return error
}

function notify(message, type = 'none') {
  uni.showToast({ title: message, icon: type, duration: 2500 })
}

function redirectToLogin() {
  if (!isAuthPage()) {
    uni.reLaunch({ url: LOGIN_PAGE })
  }
}

function clearStudentSession(requestSession) {
  const userStore = getUserStore()
  if (userStore) {
    if (requestSession?.snapshot && !isCurrentRequestSession(requestSession)) return false
    userStore.logout('auth-failure')
  } else {
    if (requestSession?.snapshot) return false
    uni.removeStorageSync('auth_token')
  }
  redirectToLogin()
  return true
}

function markNotified(error) {
  error.requestNotified = true
  return error
}

function suppressRequestError(error) {
  error.requestSuppressed = true
  return error
}

/**
 * 页面层统一使用的错误展示入口。
 * request 已展示过或已标记为旧会话/已处理的错误不会重复弹 Toast，但页面仍可以
 * 在 catch 中保留自己的恢复逻辑，从而避免空 catch 静默吞错。
 */
export function showRequestError(error, fallback = '请求失败，请稍后重试') {
  const requestError = error instanceof Error ? error : createRequestError(fallback)
  if (!requestError.requestNotified && !requestError.requestSuppressed) {
    notify(requestError.message || fallback)
    markNotified(requestError)
  }
  return requestError
}

function handleBusinessError(code, message, requestSession) {
  const error = createRequestError(message || '请求失败，请稍后重试', { code })
  const isAuthFailure = code === 40100 || code === 40101
  const isCurrent = isCurrentRequestSession(requestSession)
  if (isAuthFailure && !isCurrent) {
    suppressRequestError(error)
  }
  if (isAuthFailure && isCurrent) {
    clearStudentSession(requestSession)
  }
  if (!isAuthFailure || isCurrent) {
    markNotified(error)
    notify(error.message)
  }
  throw error
}

/**
 * 发起 HTTP 请求。
 * @param {Object} options 请求配置
 * @returns {Promise<any>} 统一响应中的 data
 */
function request({ url, method = 'GET', data = {}, header = {}, timeout = TIMEOUT }) {
  const token = getToken()
  const requestSession = captureRequestSession(token)
  const headers = {
    'Content-Type': 'application/json',
    ...header
  }
  if (token) headers.Authorization = `Bearer ${token}`

  return new Promise((resolve, reject) => {
    uni.request({
      url: `${BASE_URL}${url}`,
      method: method.toUpperCase(),
      data: method.toUpperCase() === 'GET' ? undefined : data,
      dataType: 'json',
      header: headers,
      timeout,
      success: (res) => {
        const { statusCode, data: body } = res
        const normalizedBody = body && typeof body === 'object' ? body : {}

        if (statusCode !== 200) {
          const message = normalizedBody.message || `请求失败（${statusCode}）`
          const error = createRequestError(message, {
            code: normalizedBody.code,
            status: statusCode,
            response: res
          })
          const isAuthFailure = statusCode === 401 || statusCode === 403
          const isCurrent = isCurrentRequestSession(requestSession)
          if (isAuthFailure && !isCurrent) {
            suppressRequestError(error)
          }
          if (isAuthFailure && isCurrent) {
            clearStudentSession(requestSession)
          }
          if (!isAuthFailure || isCurrent) {
            markNotified(error)
            notify(message)
          }
          reject(error)
          return
        }

        if (Object.prototype.hasOwnProperty.call(normalizedBody, 'code')) {
          if (normalizedBody.code === 0) {
            resolve(normalizedBody.data)
          } else {
            try {
              handleBusinessError(normalizedBody.code, normalizedBody.message, requestSession)
            } catch (error) {
              reject(error)
            }
          }
          return
        }

        resolve(body)
      },
      fail: (err) => {
        const error = createRequestError('网络连接失败，请检查网络后重试', {
          cause: err,
          isNetworkError: true
        })
        markNotified(error)
        notify(error.message)
        reject(error)
      }
    })
  })
}

/** GET 请求。 */
export function get(url, params = {}, options = {}) {
  const query = Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
    .join('&')
  return request({ url: query ? `${url}?${query}` : url, method: 'GET', ...options })
}

/** POST 请求。 */
export function post(url, data = {}, options = {}) {
  return request({ url, method: 'POST', data, ...options })
}

/** PUT 请求。 */
export function put(url, data = {}) {
  return request({ url, method: 'PUT', data })
}

/** DELETE 请求。 */
export function del(url, data = {}) {
  return request({ url, method: 'DELETE', data })
}

/**
 * 分页请求辅助函数。
 * @param {Function} apiFn 接收分页参数并返回分页 data 的函数
 * @param {Object} params 其他查询参数
 * @param {number} page 页码
 * @param {number} pageSize 每页数量
 */
export async function paginate(apiFn, params = {}, page = 1, pageSize = DEFAULT_PAGE_SIZE) {
  const result = await apiFn({ ...params, page, page_size: pageSize })
  const list = result?.list ?? []
  const total = result?.total ?? list.length
  const actualPageSize = result?.page_size ?? pageSize

  return {
    list,
    total,
    page: result?.page ?? page,
    page_size: actualPageSize,
    hasMore: page * actualPageSize < total
  }
}

export { BASE_URL }
export default request
