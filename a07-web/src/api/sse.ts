// AI-assisted
/**
 * SSE 流式客户端（T-007 Step 7.3）：fetch + ReadableStream 自行解析
 * `event: <type>\ndata: <json>\n\n` 帧格式（docs/03 §4），回调分发到 pinia chat store。
 *
 * 不用 EventSource：EventSource 只支持 GET，而分析接口是 POST + JWT + JSON body。
 */
import { isSseEventType, type AgentEvent, type AnalyzeRequest, type SseEventType } from '../types/agent'
import { TOKEN_STORAGE_KEY } from './http'

/** S4 会话与任务的 Agent 代理端点（契约：前端 → a07-server /api/chat/analyze → 引擎）。 */
export const ANALYZE_ENDPOINT = '/api/chat/analyze'

export type SSEEventCallback = (event: AgentEvent) => void

/** 读取 token：storage 被浏览器安全策略禁用（SecurityError）时降级为未登录态，而非崩溃。 */
function readToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY)
  } catch {
    return null
  }
}

/**
 * 帧解析器（纯逻辑，便于离线验证）：按空行 `\n\n` 分帧，帧内逐行取 `event:`/`data:`，
 * 跨 chunk 的半帧在 buffer 中缓冲。返回的函数吃增量文本。
 */
export function createSSEParser(onEvent: (type: SseEventType, data: unknown) => void): (chunk: string) => void {
  let buffer = ''
  return (chunk: string) => {
    buffer += chunk
    let separator = buffer.indexOf('\n\n')
    while (separator !== -1) {
      const frame = buffer.slice(0, separator)
      buffer = buffer.slice(separator + 2)
      dispatchFrame(frame, onEvent)
      separator = buffer.indexOf('\n\n')
    }
    // 不完整的尾帧留在 buffer，等下一个 chunk 拼齐
  }
}

function dispatchFrame(frame: string, onEvent: (type: SseEventType, data: unknown) => void): void {
  let type: string | null = null
  const dataLines: string[] = []
  for (const rawLine of frame.split('\n')) {
    const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine
    if (line.length === 0 || line.startsWith(':')) continue // 空行 / SSE 注释
    if (line.startsWith('event:')) {
      type = line.slice('event:'.length).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).replace(/^ /, ''))
    }
    // 其余字段（id:/retry:）协议未用，忽略
  }
  if (type === null || dataLines.length === 0) return

  if (!isSseEventType(type)) {
    // 契约白名单外的事件：不渲染也不崩，留下排查痕迹（契约变更应走 docs/api 流程）
    console.warn(`[sse] 收到契约外事件类型 "${type}"，已忽略`)
    return
  }
  let data: unknown
  try {
    data = JSON.parse(dataLines.join('\n'))
  } catch {
    console.warn(`[sse] 事件 "${type}" 的 data 不是合法 JSON，已忽略`)
    return
  }
  onEvent(type, data)
}

export interface AnalyzeStreamOptions {
  signal?: AbortSignal
  onEvent: SSEEventCallback
}

/**
 * 发起分析并消费 SSE 流：正常结束时返回；网络失败/非 2xx 抛出带可读信息的 Error
 * （调用方负责把错误呈现到消息流，绝不允许白屏）。
 */
export async function analyzeStream(req: AnalyzeRequest, options: AnalyzeStreamOptions): Promise<void> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  }
  const token = readToken()
  if (token) headers.Authorization = `Bearer ${token}`

  let response: Response
  try {
    response = await fetch(ANALYZE_ENDPOINT, {
      method: 'POST',
      headers,
      body: JSON.stringify(req),
      signal: options.signal,
    })
  } catch (err) {
    if (options.signal?.aborted) throw err // 主动取消：交由调用方按"已中止"处理
    throw new Error(
      `无法连接业务服务（请求 ${ANALYZE_ENDPOINT} 失败）。请确认 a07-server 已在 8080 端口启动${err instanceof Error && err.message ? `（${err.message}）` : ''}`,
    )
  }

  if (!response.ok) {
    let detail = ''
    try {
      const body: unknown = await response.json()
      if (typeof body === 'object' && body !== null) {
        const rec = body as Record<string, unknown>
        if (typeof rec.message === 'string') detail = rec.message
      }
    } catch {
      // 响应体不是 JSON：忽略，仅展示状态码
    }
    if (response.status === 401) {
      // 与 axios 拦截器同语义（BUG-013）：SSE 通道遇 401 也要清凭据并回登录页，而非只弹文案
      try {
        localStorage.removeItem(TOKEN_STORAGE_KEY)
        localStorage.removeItem('a07_role')
      } catch {
        // storage 不可用时跳过清理
      }
      if (window.location.pathname !== '/login') {
        window.location.assign('/login')
      }
      throw new Error('登录已失效（401），请重新登录后再发起分析')
    }
    // 502/504 两种来源要区分（BUG-012）：body 带 message = a07-server 报"引擎不可达"；
    // 无 body 信息 = Vite 代理连不上 8080，业务服务本身未启动
    if (response.status === 502 || response.status === 504) {
      if (detail) {
        throw new Error(`服务链路异常（HTTP ${response.status}）：${detail}`)
      }
      throw new Error(
        `无法连接业务服务（HTTP ${response.status}）：通常是 a07-server 未在 8080 端口启动，请先启动业务服务再重试`,
      )
    }
    throw new Error(`业务服务返回 HTTP ${response.status}${detail ? `：${detail}` : ''}`)
  }
  if (!response.body) {
    throw new Error('当前浏览器不支持流式响应（缺少 ReadableStream）')
  }

  // 统一换行符为 \n 后喂给解析器（防御代理层输出 CRLF 帧分隔）
  const feed = createSSEParser((type, data) => options.onEvent({ type, data } as AgentEvent))
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      feed(decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n'))
    }
    const tail = decoder.decode()
    if (tail.length > 0) feed(tail.replace(/\r\n/g, '\n'))
  } finally {
    reader.releaseLock()
  }
}
