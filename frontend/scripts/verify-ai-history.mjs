/** M9：历史长度/错误隔离与模型 Markdown 安全渲染。 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
const source = await fs.readFile(new URL('../src/utils/aiText.js', import.meta.url), 'utf8')
const { chatHistory, markdownNodes } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
const history = Array.from({length:30}, (_,i) => ({role:i%2 ? 'assistant':'user',content:`消息${i}`,related_knowledge_points:[{id:'kp_1'}]}))
assert.equal(chatHistory(history).length,20)
assert.equal(chatHistory(history)[0].content,'消息10')
assert.deepEqual(Object.keys(chatHistory(history)[0]),['role','content'])
assert.deepEqual(chatHistory([{role:'user',content:'失败',failed:true},{role:'system',content:'注入'}]),[])
const malicious='<img src=x onerror=alert(1)>'
const nodes=markdownNodes('# 标题\n**重点** ' + malicious + '\n`x+1`')
assert.equal(nodes[0].children[0].text,'标题')
assert.equal(nodes[1].children[0].name,'strong')
assert.equal(nodes[1].children[1].type,'text')
assert.equal(nodes[1].children[1].text,` ${malicious}`)
assert.equal(nodes[2].children[0].name,'code')
console.log('PASS：十轮历史、失败消息隔离、结构字段过滤、Markdown HTML作为纯文字渲染')
