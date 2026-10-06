# UniApp 客户端前端初始化交付总结

> 交付日期：2026-07-17
> 对应需求：初始化 UniApp（Vue 3）客户端前端，目标平台 H5 + 微信小程序

---

## 一、交付内容

### 1.1 项目结构

```
frontend/
├── index.html                  # H5 入口 HTML
├── vite.config.js              # Vite 配置（uni-app 插件）
├── package.json                # 依赖声明（npm）
├── src/
│   ├── main.js                 # UniApp 入口，挂载 Pinia
│   ├── App.vue                 # 根组件（全局生命周期 + 全局样式）
│   ├── manifest.json           # 应用配置（H5 + 微信小程序）
│   ├── pages.json              # 路由 & TabBar 配置（13 页面）
│   ├── uni.scss                # 全局 SCSS 变量 + uni-ui 主题
│   ├── store/
│   │   ├── user.js             # Pinia — 用户信息/token/登录态
│   │   └── app.js              # Pinia — α 向量/诊断/loading/toast
│   ├── utils/
│   │   └── request.js          # uni.request 统一封装
│   └── pages/
│       ├── index/index.vue          # 首页（TabBar）
│       ├── learning/index.vue       # 学习总览（TabBar）
│       ├── diagnosis/index.vue      # 诊断总览（TabBar）
│       ├── social/index.vue         # 社交首页（TabBar）
│       ├── mine/index.vue           # 我的（TabBar）
│       ├── learning/detail.vue      # 知识点详情
│       ├── path/path.vue            # 学习路径
│       ├── quiz/quiz.vue            # 答题
│       ├── diagnosis/explain.vue    # AI 解读
│       ├── chat/index.vue           # AI 答疑
│       ├── social/achievements.vue  # 成就列表
│       ├── report/report.vue        # 周报
│       └── settings/index.vue       # 设置
```

### 1.2 路由 & TabBar

| Tab | 路径 | 标题 |
|-----|------|------|
| 首页 | `pages/index/index` | 首页 |
| 学习 | `pages/learning/index` | 学习总览 |
| 诊断 | `pages/diagnosis/index` | 认知诊断 |
| 社交 | `pages/social/index` | 社交 |
| 我的 | `pages/mine/index` | 我的 |

二级页面从对应 Tab 页面通过 `uni.navigateTo` 跳转。

### 1.3 技术栈

- **框架**: UniApp（Vue 3 + Vite）
- **组件库**: @dcloudio/uni-ui
- **状态管理**: Pinia
- **样式**: SCSS（全局变量 + uni-ui 主题定制）
- **语法**: `<script setup>` + `<view>`/`<text>`（符合总则规范）

### 1.4 关键实现

#### request 工具（`src/utils/request.js`）

- 基于 `uni.request` 封装
- 统一处理 `{code, data, message}` 响应
- `code === 0` → 返回 `data`；非 0 → `uni.showToast` + reject
- 提供 `get/post/put/del` 便捷方法
- `paginate(fn, params)` 自动解包分页结构 `{list, total, page, page_size}` 并在前端计算 `hasMore`（后端分页响应不含 hasMore，按 `page * page_size < total` 判定）
- 自动注入 `Authorization: Bearer <token>`（从 Pinia user store 读取）
- 基础 URL：`http://localhost:8000`

#### Pinia Store

- **user store**：`userId` / `username` / `name` / `token`，含 `restoreToken()` / `logout()`
- **app store**：`alphaVector` / `lastDiagnosedAt` / `loading`，含 `masteredPoints` / `weakPoints` / `masteryRate` 计算属性

---

## 二、质量门禁自查

- [x] 代码能运行（`npx uni build -p h5` 构建成功）
- [x] 符合总则全部规范（`<script setup>` / `<view>` `<text>` / 不硬编码 / 标识符英文注释中文）
- [x] 没有引入新依赖（仅使用总则指定的 uni-ui、pinia、Vue 3）
- [x] 接口返回格式符合统一响应模型（`{code, data, message}`）
- [x] 没有硬编码密钥/密码/连接串
- [x] 文件放在正确的目录下（`frontend/src/`）
- [x] 关键函数有 docstring
- [x] 错误处理完善（try-catch + toast 降级）

---

## 三、待完成事项

| 项目 | 说明 | 优先级 |
|------|------|--------|
| TabBar 图标 | 当前为纯文字模式，需补充 10 个 PNG 图标到 `src/static/tabs/` | P1 |
| API 对接 | 所有页面已预留 `get/post` 调用，标记 `TODO` 待后端接口就绪后解除 | P0 |
| 登录页 | 当前无登录页面，token 通过 Pinia store 手动 set；需补充登录/注册页面 | P0 |
| 微信小程序配置 | `manifest.json` 中 `mp-weixin.appid` 需填入真实 AppID | P1 |
| .env 配置 | 当前 BASE_URL 硬编码在 request.js 中，后续迁移到 `.env` 统一管理 | P2 |
| 微信 JS-SDK | `index.html` 中预留了微信 JS-SDK 引用注释 | P3 |

---

## 四、启动命令

```bash
cd frontend

# H5 开发
npm run dev:h5

# 微信小程序开发
npm run dev:mp-weixin

# H5 构建
npm run build:h5

# 微信小程序构建
npm run build:mp-weixin
```
