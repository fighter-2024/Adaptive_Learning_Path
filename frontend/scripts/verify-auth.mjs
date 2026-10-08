import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'

const root = fileURLToPath(new URL('..', import.meta.url))

async function read(relativePath) {
  return readFile(resolve(root, relativePath), 'utf8')
}

const checks = [
  ['request uses build-time API configuration', (request) => request.includes('import.meta.env.VITE_API_BASE_URL')],
  ['request does not use CommonJS require', (request) => !request.includes('require(')],
  ['student request attaches Bearer token', (request) => request.includes('Authorization = `Bearer ${token}`')],
  ['student request handles auth failure', (request) => /clearStudentSession\(requestSession\)/.test(request)],
  ['student app validates session on launch', (app) => app.includes('initializeSession()')],
  ['student auth pages are registered', (pages) => pages.includes('pages/auth/login') && pages.includes('pages/auth/register')],
  ['admin store rejects non-admin roles', (adminStore) => adminStore.includes("res?.role !== 'admin'")],
  ['admin router protects management routes', (router) => router.includes('requiresAuth') && router.includes('fetchAdminInfo()')]
]

const contents = {
  request: await read('src/utils/request.js'),
  app: await read('src/App.vue'),
  pages: await read('src/pages.json'),
  adminStore: await read('../admin/src/stores/admin.js'),
  router: await read('../admin/src/router/index.js')
}

// Each check is evaluated explicitly so a future edit cannot silently remove a guard.
const results = [
  checks[0][1](contents.request),
  checks[1][1](contents.request),
  checks[2][1](contents.request),
  checks[3][1](contents.request),
  checks[4][1](contents.app),
  checks[5][1](contents.pages),
  checks[6][1](contents.adminStore),
  checks[7][1](contents.router)
]

if (results.some((passed) => !passed)) {
  checks.forEach(([label], index) => {
    console.log(`${results[index] ? 'PASS' : 'FAIL'} ${label}`)
  })
  process.exitCode = 1
} else {
  console.log(`PASS ${results.length} authentication configuration checks`)
}
