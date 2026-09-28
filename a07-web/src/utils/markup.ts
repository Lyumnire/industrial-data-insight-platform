// AI-assisted
/**
 * P1 简版流式 Markdown 渲染（T-007 Step 7.4：先 v-html 简版，P2 换增量解析器）。
 *
 * 安全约定：先整体 HTML 转义，再施加白名单标记（标题/列表/加粗/行内代码/换行），
 * LLM 输出中的任何 HTML 字面量都会被转义显示，不存在注入面（红线 R2 的前端侧配合）。
 */

const HTML_ESCAPES: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
}

function escapeHtml(source: string): string {
  return source.replace(/[&<>"']/g, (char) => HTML_ESCAPES[char] ?? char)
}

function renderInline(escaped: string): string {
  return escaped
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
}

/** 把流式拼接的纯文本渲染为受控 HTML 片段（供 v-html 使用）。 */
export function renderSimpleMarkdown(source: string): string {
  const lines = escapeHtml(source).split(/\r?\n/)
  const html: string[] = []
  let listOpen = false

  const closeList = (): void => {
    if (listOpen) {
      html.push('</ul>')
      listOpen = false
    }
  }

  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed.length === 0) {
      closeList()
      continue
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(trimmed)
    if (heading) {
      closeList()
      const level = heading[1]?.length ?? 1
      html.push(`<h${level + 2}>${renderInline(heading[2] ?? '')}</h${level + 2}>`)
      continue
    }
    const listItem = /^[-*]\s+(.*)$/.exec(trimmed)
    if (listItem) {
      if (!listOpen) {
        html.push('<ul>')
        listOpen = true
      }
      html.push(`<li>${renderInline(listItem[1] ?? '')}</li>`)
      continue
    }
    closeList()
    html.push(`<p>${renderInline(trimmed)}</p>`)
  }
  closeList()
  return html.join('\n')
}
