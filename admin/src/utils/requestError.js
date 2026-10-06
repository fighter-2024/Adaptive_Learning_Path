/** 请求异常的统一可展示分类。 */
export function getRequestErrorInfo(error) {
  const response = error?.response
  const body = response?.data || {}
  const status = error?.status ?? response?.status ?? null
  // 服务端业务码优先于 Axios 的 ERR_BAD_REQUEST 等传输层字符串。
  const code = body?.code ?? error?.code ?? null

  if (status === 401 || code === 40100) {
    return { kind: 'unauthorized', status: status || 401, code, message: body.message || error?.message || '登录已过期，请重新登录' }
  }
  if (status === 403 || code === 40101) {
    return { kind: 'forbidden', status: status || 403, code, message: body.message || error?.message || '当前账号无权访问该资源' }
  }
  if (status === 429 || code === 40901) {
    return { kind: 'rate_limited', status: status || 429, code, message: body.message || error?.message || '请求过于频繁，请稍后再试' }
  }
  if (status >= 500 || (typeof code === 'number' && code >= 50000)) {
    return { kind: 'server', status, code, message: body.message || error?.message || '服务器异常，请稍后重试' }
  }
  if (!response) {
    const timeout = error?.code === 'ECONNABORTED'
    return {
      kind: timeout ? 'timeout' : 'network',
      status: null,
      code,
      message: timeout ? '请求超时，请稍后重试' : (error?.message || '网络异常，请检查后端服务'),
    }
  }
  return { kind: 'business', status, code, message: body.message || error?.message || '请求失败，请稍后重试' }
}
