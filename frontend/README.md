# 自适应学习系统 — 学生端

学生端使用 UniApp（Vue 3 + Pinia），目标平台为 H5 和微信小程序。

## API 配置

复制 `.env.example` 为 `.env.local`：

- `VITE_API_BASE_URL`：构建时使用的后端 API 基础地址。微信小程序必须配置可访问的 HTTPS 地址。
- `VITE_API_PROXY_TARGET`：仅用于 H5 本地开发代理；不参与小程序运行时请求。

请求统一经过 `src/utils/request.js`，会自动附加 `Authorization: Bearer <token>`，解析 `{ code, data, message }`，并在 401/403 时清理学生登录态、跳转登录页。

## 认证闭环

应用启动时先恢复本地 Token，再调用 `/auth/me` 校验；只有确认角色为 `student` 才能进入受保护页面。登录、注册、退出登录页面分别位于 `src/pages/auth/`，全局导航拦截器负责保护学生页面。

## 验证

```bash
npm run verify:auth
npm run build:h5
npm run build:mp-weixin
```
