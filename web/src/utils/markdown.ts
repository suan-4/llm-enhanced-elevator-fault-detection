/* 与早期版本一致：模型最终正文按 Markdown 渲染。 */
import { marked } from 'marked'

marked.setOptions({ gfm: true, breaks: true })

export function renderMarkdown(text: string): string {
  if (!text) return ''
  try {
    const html = marked.parse(text, { async: false }) as string
    // 离线终端只渲染报告排版，去掉可能被模型带出的脚本/事件属性
    return html
      .replace(/<script[\s\S]*?<\/script>/gi, '')
      .replace(/\son\w+="[^"]*"/gi, '')
      .replace(/\son\w+='[^']*'/gi, '')
  } catch {
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  }
}
