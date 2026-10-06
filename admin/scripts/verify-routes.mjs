import { access, readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { resolve } from 'node:path'

const root = fileURLToPath(new URL('..', import.meta.url))
const routerPath = resolve(root, 'src/router/index.js')
const routerSource = await readFile(routerPath, 'utf8')

const expectedRoutes = [
  ['/dashboard', 'dashboard', 'Dashboard.vue'],
  ['/knowledge-graph', 'knowledgeGraph', 'KnowledgeGraph.vue'],
  ['/questions', 'questions', 'Questions.vue']
]

if (routerSource.includes("import('@/views/' +")) {
  throw new Error('发现未解析的字符串拼接式 Vue 动态导入')
}

for (const [path, routeKey, fileName] of expectedRoutes) {
  const componentImport = `${routeKey}: () => import('@/views/${fileName}')`
  const routeMapping = new RegExp(`path:\\s*'${path}',\\s*routeKey:\\s*'${routeKey}'`)
  if (!routerSource.includes(componentImport)) {
    throw new Error(`${path} 缺少静态组件导入：${fileName}`)
  }
  if (!routeMapping.test(routerSource)) {
    throw new Error(`${path} 缺少 menuRoutes 显式映射`)
  }
  await access(resolve(root, `src/views/${fileName}`))
}

console.log(`PASS ${expectedRoutes.length} management route component mappings`)
