import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { createPinia, setActivePinia } from 'pinia'

const root = process.cwd()
const appSource = await readFile(resolve(root, 'src/App.vue'), 'utf8')
const scriptMatch = appSource.match(/<script setup>([\s\S]*?)<\/script>/)
assert.ok(scriptMatch, 'App.vue must contain a script setup block')

const requiredSourceChecks = [
  ['启动前恢复持久化 Token', /if \(!userStore\.token\) userStore\.restoreToken\(\)/.test(scriptMatch[1])],
  ['启动回调捕获会话快照', /const startupSession = userStore\.getSessionSnapshot\(\)/.test(scriptMatch[1])],
  ['旧启动结果受会话归属保护', /isSessionSnapshotCurrentOrAuthFailure\(startupSession\)/.test(scriptMatch[1])],
  ['生产启动仍调用真实初始化', /userStore\.initializeSession\(\)/.test(scriptMatch[1])],
  ['当前认证失败仍保留登录页路径', /uni\.reLaunch\(\{ url: LOGIN_PAGE \}\)/.test(scriptMatch[1])]
]

for (const [label, passed] of requiredSourceChecks) {
  assert.equal(passed, true, label)
}

globalThis.__VITE_API_BASE_URL = ''
const storage = new Map()
const pending = []
const pendingWaiters = new Set()
const redirects = []
const toasts = []
const navigations = []
const interceptors = new Map()
let currentRoute = 'pages/auth/login'

globalThis.getCurrentPages = () => [{ route: currentRoute }]
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
    currentRoute = String(options?.url || '').replace(/^\//, '')
  },
  switchTab(options) {
    navigations.push({ method: 'switchTab', ...options })
    currentRoute = String(options?.url || '').replace(/^\//, '')
  },
  addInterceptor(method, definition) {
    interceptors.set(method, definition)
  },
  request(options) {
    pending.push(options)
    for (const wake of pendingWaiters) wake()
    pendingWaiters.clear()
  }
}

const { useUserStore } = await import('@/store/user')
await import('@/utils/request')

let appImportSequence = 0
let appModuleUrl
const tempDirectory = await mkdtemp(join(tmpdir(), 'reasonix-app-startup-'))
try {
  const appModulePath = join(tempDirectory, 'App-under-test.mjs')
  await writeFile(appModulePath, scriptMatch[1], 'utf8')
  appModuleUrl = pathToFileURL(appModulePath).href

  function tick() {
    return new Promise((resolveTick) => setImmediate(resolveTick))
  }

  async function settle() {
    await tick()
    await tick()
  }

  function reset({ token = '' } = {}) {
    storage.clear()
    pending.length = 0
    redirects.length = 0
    toasts.length = 0
    navigations.length = 0
    interceptors.clear()
    if (token) storage.set('auth_token', token)
    setActivePinia(createPinia())
    return useUserStore()
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
    assert.fail(`expected pending request ${path}`)
  }

  function loginResponse(token) {
    return { code: 0, data: { token } }
  }

  function userResponse(userId) {
    return { code: 0, data: { user_id: userId, username: userId, name: userId, role: 'student' } }
  }

  async function loadApp(label) {
    globalThis.__M0AppLifecycle = { launch: [], show: [], hide: [] }
    appImportSequence += 1
    await import(`${appModuleUrl}?case=${appImportSequence}-${encodeURIComponent(label)}`)
    assert.equal(globalThis.__M0AppLifecycle.launch.length, 1, 'production App.vue must register one onLaunch callback')
    return globalThis.__M0AppLifecycle.launch[0]
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

  async function invokeCurrentBNavigation() {
    const interceptor = interceptors.get('switchTab')
    assert.ok(interceptor, 'production App.vue must install the switchTab guard')
    const options = { url: '/pages/index/index' }
    assert.deepEqual(interceptor.invoke(options), options, 'authenticated B navigation must remain allowed')
    currentRoute = 'pages/index/index'
  }

  const staleCases = [
    ['late startup A success', userResponse('student-a'), 200],
    ['late startup A HTTP401', { detail: 'controlled old startup 401' }, 401],
    ['late startup A HTTP403', { detail: 'controlled old startup 403' }, 403],
    ['late startup A business40100', { code: 40100, message: 'controlled old startup expired' }, 200],
    ['late startup A business40101', { code: 40101, message: 'controlled old startup role' }, 200]
  ]
  const cases = []

  for (const [name, response, statusCode] of staleCases) {
    const store = reset({ token: 'student-a-token' })
    currentRoute = 'pages/auth/login'
    const launch = await loadApp(name)
    launch()
    const oldRequest = await waitForPending('/auth/me', (request) => request.header?.Authorization === 'Bearer student-a-token')

    store.logout()
    await completeLogin(store, 'student-b', 'student-b-token')
    await invokeCurrentBNavigation()
    redirects.length = 0
    toasts.length = 0

    respond(oldRequest, response, statusCode)
    await settle()
    const passed = store.userInfo.userId === 'student-b'
      && store.token === 'student-b-token'
      && storage.get('auth_token') === 'student-b-token'
      && redirects.length === 0
      && toasts.length === 0
    cases.push({
      name,
      passed,
      actual: {
        user: store.userInfo.userId,
        token_preserved: store.token === 'student-b-token',
        persisted_token_preserved: storage.get('auth_token') === 'student-b-token',
        redirects: [...redirects],
        toasts: [...toasts]
      },
      expected: 'old startup completion has no navigation or notification side effect on B'
    })
  }

  // A newer B initialization remains in flight when the old startup request
  // settles; the startup callback must not clear or replay that Promise.
  {
    const store = reset({ token: 'student-a-token' })
    currentRoute = 'pages/auth/login'
    const launch = await loadApp('B initialization remains pending')
    launch()
    const oldRequest = await waitForPending('/auth/me', (request) => request.header?.Authorization === 'Bearer student-a-token')
    store.logout()
    store.setToken('student-b-token')
    const bInitialization = store.initializeSession()
    const bRequest = await waitForPending('/auth/me', (request) => request.header?.Authorization === 'Bearer student-b-token')
    let bSettled = false
    bInitialization.then(() => { bSettled = true })
    currentRoute = 'pages/index/index'
    redirects.length = 0

    respond(oldRequest, userResponse('student-a'))
    await settle()
    const oldDidNotInterruptB = !bSettled && redirects.length === 0
    respond(bRequest, userResponse('student-b'))
    const bResult = await bInitialization
    cases.push({
      name: 'B initialization remains pending after old startup completion',
      passed: oldDidNotInterruptB && bResult === true && store.userInfo.userId === 'student-b',
      actual: { old_did_not_interrupt_b: oldDidNotInterruptB, b_result: bResult, user: store.userInfo.userId },
      expected: 'old startup result does not clear or replace B initialization'
    })
  }

  // Logout without a replacement session must not be resurrected or navigated
  // by the old startup callback.
  {
    const store = reset({ token: 'student-a-token' })
    currentRoute = 'pages/index/index'
    const launch = await loadApp('logout without replacement session')
    launch()
    const oldRequest = await waitForPending('/auth/me')
    store.logout()
    redirects.length = 0
    respond(oldRequest, userResponse('student-a'))
    await settle()
    cases.push({
      name: 'logout without replacement session',
      passed: !store.isLoggedIn && !storage.has('auth_token') && redirects.length === 0,
      actual: { logged_in: store.isLoggedIn, persisted_token: storage.get('auth_token') || '', redirects: [...redirects] },
      expected: 'old startup result does not resurrect identity or replay navigation'
    })
  }

  // Current failures retain their normal rejection/redirect behavior.
  for (const [name, response, statusCode] of [
    ['current startup expired', { detail: 'current expired' }, 401],
    ['current startup admin rejected', { code: 0, data: { user_id: 'admin', username: 'admin', role: 'admin' } }, 200]
  ]) {
    const store = reset({ token: 'current-token' })
    currentRoute = 'pages/index/index'
    const launch = await loadApp(name)
    launch()
    respond(await waitForPending('/auth/me'), response, statusCode)
    await settle()
    cases.push({
      name,
      passed: !store.isLoggedIn && !storage.has('auth_token') && redirects.length > 0,
      actual: { logged_in: store.isLoggedIn, redirects: [...redirects] },
      expected: 'current invalid/admin identity is rejected and login navigation remains'
    })
  }

  // A valid startup still restores the user and completes the normal public
  // page-to-home navigation.
  {
    const store = reset({ token: 'student-a-token' })
    currentRoute = 'pages/auth/login'
    const launch = await loadApp('normal valid startup recovery')
    launch()
    respond(await waitForPending('/auth/me'), userResponse('student-a'))
    await settle()
    cases.push({
      name: 'normal valid startup recovery',
      passed: store.isLoggedIn && store.userInfo.userId === 'student-a' && navigations.some((item) => item.url === '/pages/index/index'),
      actual: { logged_in: store.isLoggedIn, user: store.userInfo.userId, navigations: [...navigations] },
      expected: 'valid persisted student session is restored and public startup enters home'
    })
  }

  // Network failures remain retryable rather than being converted into a
  // permanent auth state; the existing startup navigation path is retained.
  {
    const store = reset({ token: 'student-a-token' })
    currentRoute = 'pages/index/index'
    const launch = await loadApp('network failure retry')
    launch()
    const request = await waitForPending('/auth/me')
    fail(request)
    await settle()
    const retry = store.initializeSession()
    respond(await waitForPending('/auth/me'), userResponse('student-a'))
    const retryResult = await retry
    cases.push({
      name: 'network failure retry',
      passed: retryResult === true && store.isLoggedIn,
      actual: { retry_result: retryResult, logged_in: store.isLoggedIn, redirects: [...redirects] },
      expected: 'network failure does not poison later session validation'
    })
  }

  const failed = cases.filter((item) => !item.passed).length
  const evidence = {
    checked_at: new Date().toISOString(),
    method: 'actual production App.vue script setup extracted unchanged; actual user.js/request.js + Vue/Pinia; actual UniApp lifecycle imports mapped only to callback capture; controlled uni.request callbacks',
    cases,
    failed
  }
  console.log(JSON.stringify(evidence, null, 2))
  assert.equal(failed, 0, 'App startup session-isolation gate failed')
} finally {
  await rm(tempDirectory, { recursive: true, force: true })
}
