import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createPinia, setActivePinia } from 'pinia'

const root = process.cwd()
const userSource = readFileSync(resolve(root, 'src/store/user.js'), 'utf8')
const requestSource = readFileSync(resolve(root, 'src/utils/request.js'), 'utf8')

const requiredSourceChecks = [
  ['初始化不再直接把 async IIFE 赋给缓存', !/initializationPromise\s*=\s*\(async\s*\(/.test(userSource)],
  ['初始化先保存 run Promise 再写入缓存', /const promise = run\(\)[\s\S]*?initializationPromise = promise/.test(userSource)],
  ['初始化清理按 Promise 身份保护', /if \(initializationPromise === promise\) initializationPromise = null/.test(userSource)],
  ['无 token 分支仍返回未登录', /if \(!tokenAtStart\) return false/.test(userSource)],
  ['会话快照可被请求封装读取', /function getSessionSnapshot\(\)[\s\S]*?version: sessionVersion/.test(userSource)],
  ['登录在 POST 前建立生命周期', /const loginTokenAtStart = token\.value[\s\S]*?const loginVersion = beginSessionChange\('login'\)/.test(userSource)],
  ['退出会话会使旧请求失效', /function logout\([^)]*\)[\s\S]*?beginSessionChange\(reason\)/.test(userSource)],
  ['守卫捕获所属会话快照', /async function ensureAuthenticated\(redirect = true\)\s*\{\s*const guardSession = getSessionSnapshot\(\)/.test(userSource)],
  ['旧守卫仅在所属会话失败时导航', /function isSessionSnapshotCurrentOrAuthFailure[\s\S]*?sessionChangeReason === 'auth-failure'/.test(userSource) && /const guardOwnsFailure = isSessionSnapshotCurrentOrAuthFailure\(guardSession\)/.test(userSource)],
  ['当前用户接口仍由 fetchCurrentUser 调用', /get\('\/auth\/me'\)/.test(userSource)],
  ['请求在响应副作用前捕获会话', /const requestSession = captureRequestSession\(token\)/.test(requestSource)],
  ['请求鉴权失败按会话快照保护', /isCurrentRequestSession\(requestSession\)/.test(requestSource)],
  ['旧错误带有统一抑制标记', /function suppressRequestError\(error\)[\s\S]*?requestSuppressed = true/.test(requestSource)],
  ['页面错误入口尊重抑制标记', /!requestError\.requestNotified && !requestError\.requestSuppressed/.test(requestSource)],
  ['旧登录过时错误带有抑制标记', /function createStaleSessionError\(\)[\s\S]*?requestSuppressed = true/.test(userSource)]
]

for (const [label, passed] of requiredSourceChecks) {
  assert.equal(passed, true, label)
}

// Import the production Pinia store and request wrapper. The custom loader only
// adapts the @ aliases and Vite's import.meta.env for this Node gate; all
// session and request behavior below comes from src/store/user.js and
// src/utils/request.js.
const { useUserStore } = await import('@/store/user')

const storage = new Map()
const pending = []
const pendingWaiters = new Set()
const toasts = []
const redirects = []

globalThis.getCurrentPages = () => [{ route: 'pages/index/index' }]
globalThis.uni = {
  getStorageSync(key) {
    return storage.get(key) || ''
  },
  setStorageSync(key, value) {
    storage.set(key, value)
  },
  removeStorageSync(key) {
    storage.delete(key)
  },
  showToast(options) {
    toasts.push(options)
  },
  reLaunch(options) {
    redirects.push(options)
  },
  request(options) {
    pending.push(options)
    for (const wake of pendingWaiters) wake()
    pendingWaiters.clear()
  }
}

const { showRequestError } = await import('@/utils/request')

function reset({ token = '' } = {}) {
  storage.clear()
  pending.length = 0
  toasts.length = 0
  redirects.length = 0
  if (token) storage.set('auth_token', token)
  setActivePinia(createPinia())
  return useUserStore()
}

function tick() {
  return new Promise((resolveTick) => setImmediate(resolveTick))
}

function getPending(path) {
  const index = pending.findIndex((request) => request.url.endsWith(path))
  assert.notEqual(index, -1, `expected pending request ${path}`)
  return pending[index]
}

async function waitForPending(path, predicate = () => true) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const request = pending.find((candidate) => candidate.url.endsWith(path) && predicate(candidate))
    if (request) return request
    await new Promise((resolveWait) => {
      const wake = () => {
        pendingWaiters.delete(wake)
        resolveWait()
      }
      pendingWaiters.add(wake)
      setTimeout(wake, 25)
    })
  }
  return getPending(path)
}

function removePending(request) {
  const index = pending.indexOf(request)
  assert.notEqual(index, -1, 'request was already settled')
  pending.splice(index, 1)
}

function respond(request, data, statusCode = 200) {
  removePending(request)
  request.success({ statusCode, data })
}

function fail(request, error = { errMsg: 'network error' }) {
  removePending(request)
  request.fail(error)
}

function loginResponse(token) {
  return { code: 0, data: { token } }
}

function userResponse(userId) {
  return { code: 0, data: { user_id: userId, username: userId, name: userId, role: 'student' } }
}

async function completeLogin(store, userId, token, requestPredicate = () => true) {
  const loginPromise = store.login(userId, 'controlled-password')
  const postRequest = await waitForPending('/auth/login', requestPredicate)
  respond(postRequest, loginResponse(token))
  const meRequest = await waitForPending(
    '/auth/me',
    (request) => request.header?.Authorization === `Bearer ${token}`
  )
  respond(meRequest, userResponse(userId))
  await loginPromise
}

async function assertCurrentAuthFailure(response, statusCode = 200) {
  const store = reset({ token: 'current-token' })
  const initialization = store.initializeSession()
  const request = await waitForPending('/auth/me')
  respond(request, response, statusCode)
  assert.equal(await initialization, false)
  assert.equal(store.token, '')
  assert.equal(store.userInfo.userId, '')
  assert.equal(storage.has('auth_token'), false)
  assert.equal(redirects.length, 1)
}

// Original M0-R2 coverage, now through the real production store/request pair.
{
  const store = reset()
  assert.equal(await store.initializeSession(), false, 'cold start without token must be unauthenticated')
  await completeLogin(store, 'student-a', 'student-a-token')
  assert.equal(store.isLoggedIn, true)
  assert.equal(store.userInfo.userId, 'student-a')
  assert.equal(storage.get('auth_token'), 'student-a-token')
}

{
  const store = reset({ token: 'student-a-token' })
  const first = store.initializeSession()
  const second = store.initializeSession()
  const request = await waitForPending('/auth/me')
  assert.equal(pending.filter((candidate) => candidate.url.endsWith('/auth/me')).length, 1)
  respond(request, userResponse('student-a'))
  assert.equal(await first, true)
  assert.equal(await second, true)
}

{
  const store = reset({ token: 'student-a-token' })
  const first = store.initializeSession()
  fail(await waitForPending('/auth/me'))
  assert.equal(await first, false)
  assert.match(store.sessionError, /网络连接失败/)

  const retry = store.initializeSession()
  respond(await waitForPending('/auth/me'), userResponse('student-a'))
  assert.equal(await retry, true)
  assert.equal(store.isLoggedIn, true)
}

await assertCurrentAuthFailure({ code: 40100, message: 'expired' })
await assertCurrentAuthFailure({ code: 40101, message: 'invalid role' })
await assertCurrentAuthFailure({ detail: 'expired' }, 401)
await assertCurrentAuthFailure({ detail: 'forbidden' }, 403)

// Current guards retain the normal unauthenticated/admin rejection behavior.
{
  const store = reset()
  assert.equal(await store.ensureAuthenticated(true), false)
  assert.equal(redirects.length, 1)
}

{
  const store = reset({ token: 'admin-token' })
  const guard = store.ensureAuthenticated(true)
  respond(await waitForPending('/auth/me'), {
    code: 0,
    data: { user_id: 'admin-user', username: 'admin-user', name: 'admin-user', role: 'admin' }
  })
  assert.equal(await guard, false)
  assert.equal(store.token, '')
  assert.equal(redirects.length, 1)
}

// A late successful login response cannot overwrite a later B login.
{
  const store = reset()
  const loginA = store.login('student-a', 'controlled-password')
  const loginARejected = assert.rejects(loginA, (error) => error.code === 'SESSION_STALE')
  const postA = await waitForPending('/auth/login')

  const loginB = store.login('student-b', 'controlled-password')
  const postB = await waitForPending('/auth/login', (request) => request !== postA)
  respond(postB, loginResponse('student-b-token'))
  respond(await waitForPending('/auth/me'), userResponse('student-b'))
  await loginB

  respond(postA, loginResponse('student-a-token'))
  await loginARejected
  assert.equal(store.token, 'student-b-token')
  assert.equal(store.userInfo.userId, 'student-b')
  assert.equal(store.isLoggedIn, true)
  assert.equal(redirects.length, 0)
}

// A late failed login response is also isolated from the later B session.
{
  const store = reset()
  const loginA = store.login('student-a', 'controlled-password')
  const loginARejected = assert.rejects(loginA, (error) => error.code === 40100)
  const postA = await waitForPending('/auth/login')
  const loginB = store.login('student-b', 'controlled-password')
  const postB = await waitForPending('/auth/login', (request) => request !== postA)
  respond(postB, loginResponse('student-b-token'))
  respond(await waitForPending('/auth/me'), userResponse('student-b'))
  await loginB

  respond(postA, { code: 40100, message: 'old login rejected' })
  await loginARejected
  assert.equal(store.token, 'student-b-token')
  assert.equal(store.userInfo.userId, 'student-b')
  assert.equal(redirects.length, 0)
  assert.equal(toasts.length, 0)
}

// A pending login cannot be resurrected by logout.
{
  const store = reset()
  const loginA = store.login('student-a', 'controlled-password')
  const loginARejected = assert.rejects(loginA, (error) => error.code === 'SESSION_STALE')
  const postA = await waitForPending('/auth/login')
  store.logout()
  respond(postA, loginResponse('student-a-token'))
  await loginARejected
  assert.equal(store.isLoggedIn, false)
  assert.equal(store.token, '')
  assert.equal(storage.has('auth_token'), false)
}

async function assertStaleInitializationResponse(response, statusCode = 200) {
  const store = reset({ token: 'student-a-token' })
  const oldInitialization = store.initializeSession()
  const oldRequest = await waitForPending('/auth/me')

  store.logout()
  await completeLogin(store, 'student-b', 'student-b-token')
  respond(oldRequest, response, statusCode)
  assert.equal(await oldInitialization, false)
  assert.equal(store.token, 'student-b-token')
  assert.equal(store.userInfo.userId, 'student-b')
  assert.equal(store.isLoggedIn, true)
  assert.equal(storage.get('auth_token'), 'student-b-token')
  assert.equal(redirects.length, 0)
  assert.equal(toasts.length, 0)
}

async function assertStaleGuardResponse(response, statusCode = 200) {
  const store = reset({ token: 'student-a-token' })
  const oldGuard = store.ensureAuthenticated(true)
  const oldRequest = await waitForPending('/auth/me')

  store.logout()
  await completeLogin(store, 'student-b', 'student-b-token')
  respond(oldRequest, response, statusCode)
  assert.equal(await oldGuard, false)
  assert.equal(store.token, 'student-b-token')
  assert.equal(store.userInfo.userId, 'student-b')
  assert.equal(store.isLoggedIn, true)
  assert.equal(redirects.length, 0)
  assert.equal(toasts.length, 0)
}

// An old guard must not clear or redirect a newer initialization that is still
// running; the B promise remains pending until its own response arrives.
{
  const store = reset({ token: 'student-a-token' })
  const oldGuard = store.ensureAuthenticated(true)
  const oldRequest = await waitForPending('/auth/me')

  store.logout()
  store.setToken('student-b-token')
  const bInitialization = store.initializeSession()
  const bRequest = await waitForPending(
    '/auth/me',
    (request) => request.header?.Authorization === 'Bearer student-b-token'
  )
  let bSettled = false
  bInitialization.then(() => { bSettled = true })

  respond(oldRequest, userResponse('student-a'))
  assert.equal(await oldGuard, false)
  await tick()
  assert.equal(bSettled, false)
  assert.equal(redirects.length, 0)
  assert.equal(toasts.length, 0)

  respond(bRequest, userResponse('student-b'))
  assert.equal(await bInitialization, true)
  assert.equal(store.userInfo.userId, 'student-b')
}

// Old /auth/me success is rejected by user.js after transport completion.
await assertStaleInitializationResponse(userResponse('student-a'))
// Old HTTP and business auth failures are rejected by request.js before any
// logout, redirect, notification, or storage mutation can affect B.
await assertStaleInitializationResponse({ detail: 'old 401' }, 401)
await assertStaleInitializationResponse({ detail: 'old 403' }, 403)
await assertStaleInitializationResponse({ code: 40100, message: 'old expired' })
await assertStaleInitializationResponse({ code: 40101, message: 'old role' })

// The complete ensureAuthenticated(true) chain is also session-owned: an old
// A guard returns false but cannot reLaunch the now-current B session.
await assertStaleGuardResponse(userResponse('student-a'))
await assertStaleGuardResponse({ detail: 'old 401' }, 401)
await assertStaleGuardResponse({ detail: 'old 403' }, 403)
await assertStaleGuardResponse({ code: 40100, message: 'old expired' })
await assertStaleGuardResponse({ code: 40101, message: 'old role' })

async function assertStaleLoginPageError(response, statusCode = 200) {
  const store = reset()
  const loginA = store.login('student-a', 'controlled-password')
  const loginAResult = loginA.then(
    () => ({ fulfilled: true }),
    (error) => ({ fulfilled: false, error })
  )
  const postA = await waitForPending('/auth/login')

  await completeLogin(store, 'student-b', 'student-b-token', (request) => request !== postA)
  respond(postA, response, statusCode)

  const result = await loginAResult
  assert.equal(result.fulfilled, false)
  assert.equal(result.error.requestSuppressed, true)
  showRequestError(result.error, '登录失败，请稍后重试')
  assert.equal(store.token, 'student-b-token')
  assert.equal(store.userInfo.userId, 'student-b')
  assert.equal(store.isLoggedIn, true)
  assert.equal(redirects.length, 0)
  assert.equal(toasts.length, 0)
}

// Page-level catch/showRequestError must preserve the request-layer decision
// for old success, HTTP auth failures, and business auth failures.
await assertStaleLoginPageError(loginResponse('student-a-token'))
await assertStaleLoginPageError({ detail: 'old 401' }, 401)
await assertStaleLoginPageError({ detail: 'old 403' }, 403)
await assertStaleLoginPageError({ code: 40100, message: 'old expired' })
await assertStaleLoginPageError({ code: 40101, message: 'old role' })

console.log('session initialization gate: PASS (real user.js/request.js; cold login, retries, stale guards, stale page errors, logout, and auth-failure isolation)')
