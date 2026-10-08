import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const pagePath = resolve(process.cwd(), 'src/pages/learning/index.vue')
const source = readFileSync(pagePath, 'utf8')
const listItem = source.match(/<uni-list-item\s+v-for="item in list"[\s\S]*?<\/uni-list-item>/)

if (!listItem) {
  throw new Error('未找到学习总览知识点列表条目')
}

const itemSource = listItem[0]
if (!/\bclickable\b/.test(itemSource)) {
  throw new Error('学习总览知识点条目必须启用 clickable')
}
if (!/@click="goDetail\(item\.id\)"/.test(itemSource)) {
  throw new Error('学习总览知识点条目必须把当前 item.id 交给 goDetail')
}
if (!/uni\.navigateTo\(\{\s*url:\s*`\/pages\/learning\/detail\?id=\$\{id\}`\s*\}\)/.test(source)) {
  throw new Error('goDetail() 必须携带真实 id 跳转到知识点详情')
}

console.log('learning list entry: PASS (clickable -> detail?id=<item.id>)')
