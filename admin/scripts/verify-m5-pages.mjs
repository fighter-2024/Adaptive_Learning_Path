import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const read = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8')
const graph = read('src/views/KnowledgeGraph.vue')
const questions = read('src/views/Questions.vue')
const request = read('src/utils/request.js')

for (const token of [
  "node.node_type === 'knowledge_point'",
  "node.node_type === 'course'",
  'relation-prerequisite',
  'relation-belongs_to',
  '正在展示局部图谱',
  'is-focus-prerequisite',
  'is-focus-dependent',
  'prerequisite_ids: relationIds.value',
  'ElMessageBox.confirm',
]) {
  assert.ok(graph.includes(token), `知识图谱页面缺少语义标记: ${token}`)
}

for (const token of [
  'questionTypeLabel(form.type)',
  'ElMessageBox.confirm',
  'importResult.errors',
  'success_count',
  'fail_count',
]) {
  assert.ok(questions.includes(token), `题库页面缺少返修要求: ${token}`)
}

for (const token of [
  "export { getRequestErrorInfo }",
  'handleAuthFailure',
  'handleForbidden',
]) {
  assert.ok(request.includes(token), `请求封装缺少错误处理: ${token}`)
}

console.log('PASS M5 page semantic smoke checks')
