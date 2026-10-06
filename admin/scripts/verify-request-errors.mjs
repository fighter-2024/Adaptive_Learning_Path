import assert from 'node:assert/strict'
import { getRequestErrorInfo } from '../src/utils/requestError.js'

const cases = [
  [{ response: { status: 401, data: { code: 40100, message: '凭证过期' } } }, 'unauthorized', 40100],
  [{ response: { status: 403, data: { code: 40101, message: '仅管理员可访问此接口' } } }, 'forbidden', 40101],
  [{ response: { status: 200, data: { code: 40001, message: '存在后继依赖' } } }, 'business', 40001],
  [{ code: 'ECONNABORTED', message: 'timeout' }, 'timeout', 'ECONNABORTED'],
  [{ message: 'Network Error' }, 'network', null],
  [{ response: { status: 500, data: { code: 50000, message: '服务器内部错误' } } }, 'server', 50000],
]

for (const [error, kind, code] of cases) {
  const actual = getRequestErrorInfo(error)
  assert.equal(actual.kind, kind)
  assert.equal(actual.code, code)
  assert.ok(actual.message)
}

console.log(`PASS ${cases.length} request error classifications`)
