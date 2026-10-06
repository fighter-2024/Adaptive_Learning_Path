/**
 * 管理端 Axios 统一封装。
 *
 * 负责 API 地址配置、管理员 Token 注入、统一响应解包，以及 401/403、
 * 业务错误和网络错误的可展示处理。
 */
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { getRequestErrorInfo } from './requestError'

export { getRequestErrorInfo }

const instance = axios.create({
  baseURL: String(import.meta.env?.VITE_API_BASE_URL || '').replace(/\/$/, ''),
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' }
})

function markNotified(error) {
  error.requestNotified = true
  return error
}

function clearAdminToken() {
  localStorage.removeItem('admin_token')
  window.dispatchEvent(new CustomEvent('admin-auth-invalid'))
}

function redirectToLogin(message) {
  ElMessage.warning(message || '登录已过期，请重新登录')
  if (window.location.pathname !== '/login') {
    window.location.assign('/login')
  }
}

function handleAuthFailure(message) {
  clearAdminToken()
  redirectToLogin(message)
}

function handleForbidden(message) {
  ElMessage.warning(message || '当前账号无权访问该资源')
}

function showRequestError(info) {
  if (info.kind === 'unauthorized') {
    handleAuthFailure(info.message)
  } else if (info.kind === 'forbidden') {
    handleForbidden(info.message)
  } else if (info.kind === 'server' || info.kind === 'timeout' || info.kind === 'network') {
    ElMessage.error(info.message)
  } else {
    ElMessage.warning(info.message)
  }
}

instance.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('admin_token')
    if (token) {
      config.headers = config.headers || {}
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

instance.interceptors.response.use(
  (response) => {
    const body = response.data
    if (!body || typeof body !== 'object' || !Object.prototype.hasOwnProperty.call(body, 'code')) {
      const error = new Error('服务返回了无法识别的数据')
      error.status = response.status
      ElMessage.error(error.message)
      markNotified(error)
      return Promise.reject(error)
    }

    if (body.code === 0) return body.data

    const error = new Error(body.message || '请求失败，请稍后重试')
    error.code = body.code
    error.status = response.status
    error.response = response
    showRequestError(getRequestErrorInfo(error))
    markNotified(error)
    return Promise.reject(error)
  },
  (error) => {
    const info = getRequestErrorInfo(error)
    error.message = info.message
    error.status = info.status
    error.code = info.code
    showRequestError(info)
    markNotified(error)
    return Promise.reject(error)
  }
)

/** 请求方法包装；响应拦截器会解包统一响应的 data。 */
const request = {
  get(url, params) {
    return instance.get(url, { params })
  },
  post(url, data) {
    return instance.post(url, data)
  },
  put(url, data) {
    return instance.put(url, data)
  },
  delete(url, config) {
    return instance.delete(url, config)
  }
}

export default request
