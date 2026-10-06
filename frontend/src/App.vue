<script setup>
import { onHide, onLaunch, onShow } from '@dcloudio/uni-app'
import { useUserStore } from '@/store/user'

const LOGIN_PAGE = '/pages/auth/login'
const PUBLIC_PAGES = new Set(['pages/auth/login', 'pages/auth/register'])
const GUARDED_NAVIGATION_METHODS = ['navigateTo', 'redirectTo', 'reLaunch', 'switchTab']

const userStore = useUserStore()
let routeGuardInstalled = false

function pagePath(url = '') {
  return String(url).split('?')[0].replace(/^\//, '')
}

function installRouteGuard() {
  if (routeGuardInstalled || typeof uni.addInterceptor !== 'function') return
  routeGuardInstalled = true

  GUARDED_NAVIGATION_METHODS.forEach((method) => {
    uni.addInterceptor(method, {
      invoke(options = {}) {
        const target = pagePath(options.url)
        if (!target || PUBLIC_PAGES.has(target)) return options
        if (userStore.authReady && userStore.isLoggedIn) return options

        // 拦截本次跳转，等 /auth/me 完成后再重放；失败时由守卫跳到登录页。
        userStore.ensureAuthenticated(true).then((allowed) => {
          if (allowed) uni[method](options)
        })
        return false
      }
    })
  })
}

onLaunch(() => {
  installRouteGuard()
  userStore.initializeSession().then((authenticated) => {
    const pages = typeof getCurrentPages === 'function' ? getCurrentPages() : []
    const current = pages[pages.length - 1]
    if (authenticated && current && PUBLIC_PAGES.has(current.route)) {
      uni.switchTab({ url: '/pages/index/index' })
    } else if (!authenticated && current && !PUBLIC_PAGES.has(current.route)) {
      uni.reLaunch({ url: LOGIN_PAGE })
    }
  })
})

onShow(() => {})
onHide(() => {})
</script>

<style lang="scss">
/* 全局样式 — 引入 uni-ui 样式 */
@import '@/uni.scss';

/* 全局 CSS 变量 */
page {
  --color-primary: #4f8cff;
  --color-success: #18bc37;
  --color-warning: #f5a623;
  --color-danger: #f36b6b;
  --color-text-primary: #2c3e50;
  --color-text-secondary: #7f8c8d;
  --color-bg: #f5f7fa;
  --color-card: #ffffff;
  --radius-base: 12rpx;
  --shadow-card: 0 2rpx 12rpx rgba(0, 0, 0, 0.08);

  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC',
    'Microsoft YaHei', sans-serif;
  font-size: 28rpx;
  color: var(--color-text-primary);
  background-color: var(--color-bg);
  box-sizing: border-box;
}
</style>
