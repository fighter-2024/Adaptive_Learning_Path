import { defineConfig, loadEnv } from 'vite'
import uni from '@dcloudio/vite-plugin-uni'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || undefined

  return {
    plugins: [uni()],
    server: {
      port: 8080,
      host: '0.0.0.0',
      ...(apiProxyTarget
        ? {
            proxy: {
              '/api': { target: apiProxyTarget, changeOrigin: true },
              '/auth': { target: apiProxyTarget, changeOrigin: true }
            }
          }
        : {})
    }
  }
})
