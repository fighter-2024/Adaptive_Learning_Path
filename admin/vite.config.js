import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// 管理端本地开发代理；目标地址通过 VITE_API_PROXY_TARGET 配置。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || undefined

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      port: 3000,
      ...(apiProxyTarget
        ? {
            proxy: {
              '/api': { target: apiProxyTarget, changeOrigin: true },
              '/auth': { target: apiProxyTarget, changeOrigin: true },
            },
          }
        : {}),
    },
  }
})
