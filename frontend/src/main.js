import { createSSRApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'

/**
 * UniApp 入口 — 创建应用实例，挂载 Pinia
 */
export function createApp() {
  const app = createSSRApp(App)
  const pinia = createPinia()
  app.use(pinia)
  return {
    app,
    pinia
  }
}
