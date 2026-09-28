// AI-assisted
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      // 业务服务 a07-server（S4 认证 + Agent SSE 代理）；前端不直连 Agent 引擎（docs/04 §4）
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        // 5173 被占时 Vite 端口漂移，而 a07-server CORS 白名单固定 5173（a07-server CorsConfig.java）。
        // 开发代理统一定为白名单源：生产无此代理（同源部署），不影响线上行为。
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            if (proxyReq.getHeader('origin')) {
              proxyReq.setHeader('origin', 'http://localhost:5173')
            }
          })
        },
      },
    },
  },
})
