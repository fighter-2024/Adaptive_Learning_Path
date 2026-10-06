import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const pagePath = resolve(process.cwd(), 'src/pages/diagnosis/index.vue')
const source = readFileSync(pagePath, 'utf8')
const match = source.match(/function goLearning\(\)\s*\{([\s\S]*?)\n\}/)

if (!match) {
  throw new Error('未找到诊断页 goLearning()')
}

const implementation = match[1]
if (!/uni\.switchTab\(\{\s*url:\s*['"]\/pages\/learning\/index['"]\s*\}\)/.test(implementation)) {
  throw new Error('goLearning() 必须使用 uni.switchTab 打开 /pages/learning/index')
}
if (/uni\.navigateTo\s*\(\{[^}]*\/pages\/learning\/index/.test(implementation)) {
  throw new Error('tabBar 学习页不得使用 uni.navigateTo')
}

console.log('diagnosis learning entry: PASS (uni.switchTab -> /pages/learning/index)')
