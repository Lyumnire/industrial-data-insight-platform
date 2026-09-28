// AI-assisted
/** 认证 store：token/role 持久化在 localStorage，登录/登出动作（T-007 Step 7.3）。 */
import { defineStore } from 'pinia'
import {
  describeHttpError,
  login as apiLogin,
  ROLE_STORAGE_KEY,
  TOKEN_STORAGE_KEY,
  type LoginRequest,
} from '../api/http'

/**
 * 解析 JWT 的 exp（秒级 Unix 时间戳）：无效/缺失返回 null（视为无法判定过期）。
 * 仅做本地过期预判（BUG-013：过期 token 令守卫放行，用户须手动退出）；
 * 服务端仍是过期判定的最终权威（401 拦截器兜底）。
 */
export function getTokenExpSeconds(token: string): number | null {
  const parts = token.split('.')
  if (parts.length !== 3 || !parts[1]) return null
  try {
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const json = decodeURIComponent(
      window
        .atob(base64)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join(''),
    )
    const payload = JSON.parse(json) as { exp?: unknown }
    return typeof payload.exp === 'number' ? payload.exp : null
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_STORAGE_KEY) ?? '',
    role: localStorage.getItem(ROLE_STORAGE_KEY) ?? '',
    /** 最近一次登录失败的可读原因（视图直接展示，避免页面层重复翻译错误） */
    loginError: '',
  }),
  getters: {
    /** 登录态 = token 存在且（能解析出 exp 时）未过期——过期 token 不再放行路由守卫。 */
    isLoggedIn: (state) => {
      if (state.token.length === 0) return false
      const exp = getTokenExpSeconds(state.token)
      if (exp === null) return true
      return exp * 1000 > Date.now()
    },
  },
  actions: {
    async login(req: LoginRequest): Promise<boolean> {
      this.loginError = ''
      try {
        const res = await apiLogin(req)
        this.token = res.token
        this.role = res.role
        localStorage.setItem(TOKEN_STORAGE_KEY, res.token)
        localStorage.setItem(ROLE_STORAGE_KEY, res.role)
        return true
      } catch (err) {
        this.loginError = describeHttpError(err)
        return false
      }
    },
    logout(): void {
      this.token = ''
      this.role = ''
      this.loginError = ''
      localStorage.removeItem(TOKEN_STORAGE_KEY)
      localStorage.removeItem(ROLE_STORAGE_KEY)
    },
  },
})
