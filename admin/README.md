# 自适应学习系统 - 管理后台

基于 Vue 3 + Vite + Element Plus 构建的管理后台（纯 JavaScript）。

## 技术栈

- **Vue 3** — Composition API + `<script setup>`
- **Vite** — 开发服务器 & 构建工具
- **Element Plus** — UI 组件库
- **Vue Router** — 路由管理
- **Pinia** — 状态管理
- **Axios** — HTTP 请求（封装在 `src/utils/request.js`）

## 项目结构

```
src/
├── main.js                # 入口
├── App.vue                # 根组件
├── utils/request.js       # axios 封装
├── stores/admin.js        # Pinia 管理员状态
├── router/index.js        # 路由配置
├── layouts/MainLayout.vue # 侧边栏布局
└── views/                 # 页面组件
    ├── Login.vue
    ├── Dashboard.vue
    ├── KnowledgeGraph.vue
    ├── Questions.vue
    ├── Students.vue
    ├── Social.vue
    ├── AiReports.vue
    └── Config.vue
```

## 启动

```bash
npm install
npm run dev       # 开发服务器 → http://localhost:3000
npm run build     # 生产构建 → dist/
```

先复制 `.env.example` 为当前环境的 `.env.local`，按部署方式配置：

- `VITE_API_BASE_URL`：生产构建使用的 API 基础地址；留空时请求当前站点的 `/api` 与 `/auth`。
- `VITE_API_PROXY_TARGET`：仅用于本地 Vite 开发代理。

管理端登录后会通过 `/auth/me` 校验角色必须为 `admin`。Token 失效或收到 401/403 时会清理本地登录态并回到登录页。
