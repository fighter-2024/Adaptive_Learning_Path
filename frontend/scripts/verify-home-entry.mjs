import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const root = process.cwd()
const homePath = resolve(root, 'src/pages/index/index.vue')
const minePath = resolve(root, 'src/pages/mine/index.vue')
const home = readFileSync(homePath, 'utf8')
const mine = readFileSync(minePath, 'utf8')

const tabBarPaths = [
  '/pages/index/index',
  '/pages/learning/index',
  '/pages/diagnosis/index',
  '/pages/social/index',
  '/pages/mine/index'
]

const failures = []
const tabBarDeclaration = home.match(/const TAB_BAR_PATHS = new Set\(\[([\s\S]*?)\]\)/)
const navigateStart = home.indexOf('function navigateTo(url, params)')
const navigateSource = navigateStart >= 0 ? home.slice(navigateStart, home.indexOf('</script>', navigateStart)) : ''

if (!tabBarDeclaration) failures.push('首页必须声明 TAB_BAR_PATHS')
if (!navigateSource) failures.push('未找到首页 navigateTo()')

for (const path of tabBarPaths) {
  if (!tabBarDeclaration?.[1].includes(`'${path}'`)) {
    failures.push(`首页 tabBar 目标缺失：${path}`)
  }
}

if (!/TAB_BAR_PATHS\.has\(path\)[\s\S]*?uni\.switchTab\(\{\s*url:\s*path\s*\}\)/.test(navigateSource)) {
  failures.push('首页 tabBar 目标必须通过 uni.switchTab 打开')
}
if (!/uni\.navigateTo\(\{\s*url:\s*params\s*\?/.test(navigateSource)) {
  failures.push('首页普通页面必须保留 uni.navigateTo')
}

const requiredDataChecks = [
  ['首页读取当前学生知识点接口', home.includes("get('/api/student/knowledge-points')")],
  ['首页返回时刷新统计', home.includes('onShow(loadStats)')],
  ['首页不再使用暂无学习记录占位文案', !home.includes('暂无学习记录')],
  ['首页不再用固定零值统计', !/todayQuestions\s*=\s*ref\(0\)|streakDays\s*=\s*ref\(0\)/.test(home)],
  ['首页账号变化时清空旧统计', home.includes('watch(() => userStore.userInfo.userId')],
  ['我的页读取当前学生知识点接口', mine.includes("get('/api/student/knowledge-points')")],
  ['我的页返回时刷新统计', mine.includes('onShow(loadStats)')],
  ['我的页明确标记未接入统计', mine.includes('未接入')],
  ['我的页不再用固定零值统计', !/totalQuestions\s*=\s*ref\(0\)|masteredKp\s*=\s*ref\(0\)|streakDays\s*=\s*ref\(0\)/.test(mine)],
  ['我的页账号变化时清空旧统计', mine.includes('watch(() => userStore.userInfo.userId')]
]

for (const [label, passed] of requiredDataChecks) {
  if (!passed) failures.push(label)
}

if (failures.length) {
  console.error('home entry/statistics gate: FAIL')
  failures.forEach((failure) => console.error(`- ${failure}`))
  process.exitCode = 1
} else {
  console.log('home entry/statistics gate: PASS (tabBar switch + current-user stats state)')
}
