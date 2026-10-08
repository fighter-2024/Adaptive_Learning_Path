/** 安全的轻量 Markdown：只生成文字节点与固定标签，不执行模型 HTML。 */
export function markdownNodes(value) {
  return String(value || '').split('\n').map(line => {
    const heading = /^(#{1,3})\s+/.test(line)
    const text = line.replace(/^#{1,3}\s+/, '').replace(/^[-*]\s+/, '• ')
    const children = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean).map(part => {
      if (part.startsWith('**') && part.endsWith('**')) return { name: 'strong', children: [{ type: 'text', text: part.slice(2, -2) }] }
      if (part.startsWith('`') && part.endsWith('`')) return { name: 'code', children: [{ type: 'text', text: part.slice(1, -1) }] }
      return { type: 'text', text: part }
    })
    return { name: 'p', attrs: { style: `margin:0 0 8px;line-height:1.7;${heading ? 'font-weight:bold;' : ''}` }, children }
  })
}

/** 仅发送契约内成功对话，去除卡片与状态，保持最近十轮。 */
export function chatHistory(messages) {
  return messages.filter(m => !m.failed && ['user', 'assistant'].includes(m.role))
    .slice(-20).map(m => ({ role: m.role, content: String(m.content).slice(0, 2000) }))
}
