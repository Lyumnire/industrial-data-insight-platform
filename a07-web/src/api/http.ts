// AI-assisted
/**
 * HTTP 客户端（T-007 Step 7.3）：axios 实例 + 统一 Authorization 拦截器 + 登录接口。
 * 全部请求走同源 `/api`，由 Vite 代理转发到 a07-server:8080（前端不直连 Agent 引擎，docs/04 §4）。
 */
import axios from 'axios'
import type { MLResultPayload, MlRunRequest } from '../types/agent'

export const TOKEN_STORAGE_KEY = 'a07_token'
export const ROLE_STORAGE_KEY = 'a07_role'

/** a07-server S1 登录契约（P1 计划 §Task 6：POST /api/auth/login → {token, role}）。 */
export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  token: string
  role: string
}

const http = axios.create({
  baseURL: '',
  // 登录等 REST 调用的超时（红线 R8）；SSE 流式通道超时语义不同，见 api/sse.ts
  timeout: 15000,
})

/** 共享 axios 实例（knowledge/metadata 等业务 API 复用同一 Authorization 拦截器）。 */
export { http }
export default http

// 请求拦截：统一携带 Authorization（存在才带，登录请求本身不带）
http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_STORAGE_KEY)
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  return config
})

// 响应拦截：401 = token 缺失/过期，清凭据并回登录页（window 级跳转避免 store/router 循环依赖）
http.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (axios.isAxiosError(error) && error.response?.status === 401) {
      localStorage.removeItem(TOKEN_STORAGE_KEY)
      localStorage.removeItem(ROLE_STORAGE_KEY)
      if (window.location.pathname !== '/login') {
        window.location.assign('/login')
      }
    }
    return Promise.reject(error)
  },
)

/**
 * 把 axios 异常翻译成用户可读信息（R8：不裸抛、不吞异常）。
 * 后端未启动是最常见故障，必须给出可操作的提示而非白屏/静默。
 * T-020 扩展：覆盖知识/元数据 CRUD 常见状态码（400/404/409/422）与超时。
 */
export function describeHttpError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    if (err.response) {
      const status = err.response.status
      const detail = extractMessage(err.response.data)
      if (status === 401) return detail || '用户名或密码错误（401），或登录已过期'
      if (status === 403) return '当前账号没有权限执行该操作（403）'
      if (status === 400) return `请求参数不合法（400）${detail ? `：${detail}` : ''}`
      if (status === 404) return `资源不存在（404）${detail ? `：${detail}` : '，可能已被删除'}`
      if (status === 409) return `编码冲突（409）${detail ? `：${detail}` : '，该 code 已存在'}`
      if (status === 422) return `数据校验失败（422）${detail ? `：${detail}` : ''}`
      // 502/504 有两种来源，必须区分（BUG-012）：
      //   a) Vite 代理连不上 8080 → a07-server 本身未启动；
      //   b) a07-server 返回 502（body 带 message）→ 业务服务活着，是引擎(8100)不可达。
      if (status === 502 || status === 504) {
        if (detail) {
          return `服务链路异常（HTTP ${status}）:${detail}`
        }
        return '服务网关错误（HTTP ' + status + '）：通常是 a07-server 未在 8080 端口启动，请先启动业务服务'
      }
      return `业务服务返回错误（HTTP ${status}）${detail ? `：${detail}` : ''}`
    }
    if (err.code === 'ECONNABORTED' || err.message.includes('timeout')) {
      return '请求超时：业务服务响应过慢，请稍后重试或检查 a07-server 状态'
    }
    return '无法连接业务服务（http://localhost:8080），请确认 a07-server 已启动后再登录'
  }
  return err instanceof Error ? err.message : '未知错误'
}

function extractMessage(data: unknown): string {
  if (typeof data === 'object' && data !== null) {
    const rec = data as Record<string, unknown>
    if (typeof rec.message === 'string' && rec.message.length > 0) return rec.message
  }
  return ''
}

/** 兼容两种响应形态：直接 {token, role} 或统一响应体 {code, message, data:{token, role}}。 */
function pickTokenPayload(data: unknown): LoginResponse | null {
  if (typeof data !== 'object' || data === null) return null
  const rec = data as Record<string, unknown>
  if (typeof rec.token === 'string' && rec.token.length > 0) {
    return {
      token: rec.token,
      role: typeof rec.role === 'string' && rec.role.length > 0 ? rec.role : 'user',
    }
  }
  return null
}

export async function login(req: LoginRequest): Promise<LoginResponse> {
  const res = await http.post<unknown>('/api/auth/login', req)
  const direct = pickTokenPayload(res.data)
  if (direct) return direct
  const nested = pickTokenPayload(
    typeof res.data === 'object' && res.data !== null ? (res.data as Record<string, unknown>).data : null,
  )
  if (nested) return nested
  throw new Error('登录响应不符合契约（未找到 token 字段），请检查 a07-server 版本')
}

// ---------- 建模工作台（P2a Task 14.4） ----------

/**
 * POST /api/agent/ml/run（引擎 MlRunRequest 契约；经 /api 代理）。
 * 响应为 ml_payload 直出（MLResultPayload）；兼容统一响应体 {code,message,data} 包裹形态。
 * 400 = 数据校验失败（detail 为用户可读信息，交由视图展示）。
 */
export async function runMl(req: MlRunRequest): Promise<MLResultPayload> {
  // 建模含沙箱冷启动（pandas/sklearn 首次加载）+ 取数 + 训练，真实耗时 15~90s：
  // 共享实例 15s 超时会误杀正常任务（BUG-029），此处单独放宽到 180s，
  // 与 Java 侧 ml-timeout-seconds=120 对齐并留出响应传输余量。
  const res = await http.post<unknown>('/api/agent/ml/run', req, { timeout: 180000 })
  const candidates: unknown[] = [res.data]
  if (typeof res.data === 'object' && res.data !== null) {
    candidates.push((res.data as Record<string, unknown>).data)
  }
  for (const candidate of candidates) {
    if (isMlResultPayload(candidate)) return candidate
  }
  throw new Error('建模响应不符合契约（缺少 taskType/modelType 字段），请检查服务版本')
}

function isMlResultPayload(value: unknown): value is MLResultPayload {
  if (typeof value !== 'object' || value === null) return false
  const rec = value as Record<string, unknown>
  return (
    typeof rec.taskId === 'string' &&
    typeof rec.modelType === 'string' &&
    (rec.taskType === 'regression' ||
      rec.taskType === 'classification' ||
      rec.taskType === 'clustering' ||
      rec.taskType === 'anomaly')
  )
}

/**
 * GET /api/catalog/tables 元数据表清单（BUG-024：Java CatalogController 读 table_metadata）。
 * 任何失败/形态不符返回 null，由调用方降级为"示例数据"硬编码选项（UI 明确标注，不伪造元数据）。
 */
export async function fetchCatalogTables(): Promise<string[] | null> {
  try {
    const res = await http.get<unknown>('/api/catalog/tables', { timeout: 5000 })
    const candidates: unknown[] = [res.data]
    if (typeof res.data === 'object' && res.data !== null) {
      candidates.push((res.data as Record<string, unknown>).data)
      candidates.push((res.data as Record<string, unknown>).tables)
    }
    for (const candidate of candidates) {
      if (Array.isArray(candidate) && candidate.every((v) => typeof v === 'string')) {
        return candidate as string[]
      }
    }
    return null
  } catch {
    return null
  }
}
