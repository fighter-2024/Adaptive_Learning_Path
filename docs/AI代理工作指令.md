# AI 代理工作指令集

> 以下指令可直接复制到 Reasonix 会话中使用，按项目阶段分类。
> **每条指令 = 一个独立会话**，完成后审 diff，验收通过再继续下一条。

---

## Phase 1 · 基础环境

### 初始化后端项目骨架

```
在当前 server/ 目录下初始化一个 FastAPI 项目骨架，要求：
1. 使用 pydantic-settings 管理配置，从 .env 读取
2. 统一响应模型：{"code": 0, "data": ..., "message": ""}
3. 路由分 admin/ 和 student/ 两组，先各放一个 health 占位接口
4. 连接 Neo4j（用 neo4j-driver）和 SQL Server（用 pyodbc），连接串从配置读
5. 代码注释用中文，标识符用英文
```

### 创建 .env 模板

```
在 server/ 下创建 .env.example 模板文件，包含以下配置项（不填真实值）：
- NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
- SQLSERVER_HOST, SQLSERVER_PORT, SQLSERVER_USER, SQLSERVER_PASSWORD, SQLSERVER_DATABASE
- LLM_PROVIDER, LLM_API_KEY, LLM_MODEL, LLM_TIMEOUT
- DINA_EM_MAX_ITERATIONS, DINA_EM_CONVERGENCE_THRESHOLD, DINA_S_INITIAL, DINA_G_INITIAL
- SECRET_KEY, JWT_EXPIRE_MINUTES
同时更新 server/app/config/ 下的配置类，确保所有项都有对应字段。
```

### 数据库建表脚本

```
根据 docs/数据库设计.md 中 SQL Server 的 11 张表定义，生成建表 SQL 脚本。
保存到 server/sql/init.sql。
要求：
- 所有 ID 前缀遵循命名规范（stu_/kp_/q_/ar_ 等）
- 索引按文档说明创建
- 唯一约束按文档说明创建
- 外键关系标注在注释中
- 包含几条示例数据的 INSERT 语句
```

### 初始化管理后台前端

```
在 admin/ 目录下用 Vue 3 + Vite + Element Plus 初始化管理后台项目。
要求：
1. 路由（7 个）：仪表盘 /dashboard、知识图谱 /knowledge-graph、题库管理 /questions、
   学生数据 /students、社交管理 /social、AI报告 /ai-reports、系统配置 /config
2. axios 封装，baseURL 指向 localhost:8000，统一拦截返回的 code 字段
3. Pinia 状态管理，存储当前管理员信息
4. 登录页占位 + 侧边栏布局（侧边栏 7 个菜单项对应上述路由）
```

### 初始化客户端前端（UniApp）

```
在当前 frontend/ 目录下用 UniApp（Vue 3）初始化项目，目标平台 H5 + 微信小程序。
用 uni-ui 组件库。封装 request 工具，统一处理 code 字段。

路由（13 页）：
- 一级 TabBar（5 个）：pages/index/index（首页）、pages/learning/index（学习总览）、
  pages/diagnosis/index（诊断总览）、pages/social/index（社交首页）、pages/mine/index（我的）
- 二级跳转（8 个）：pages/learning/detail（知识点详情）、pages/path/path（学习路径）、
  pages/quiz/quiz（答题）、pages/diagnosis/explain（AI解读）、
  pages/chat/index（AI答疑）、pages/social/achievements（成就列表）、
  pages/report/report（周报）、pages/settings/index（设置）
```

### 知识图谱数据导入

```
编写 Python 脚本，从 kg-data/data/ 下的知识点数据导入 Neo4j。
知识点节点属性：id, name, description, difficulty, estimated_time, chapter_id, sort_order
关系：PREREQUISITE（前置依赖）、BELONGS_TO（归属章节）
脚本支持：从 CSV 读取、批量创建节点和关系、去重检查。
运行前自动清空已有图谱数据（加 --force 参数才执行清空）。
```

---

## Phase 2 · 后端核心

### 用户认证（登录/注册）

```
在 server/app/routers/ 下实现用户认证：
- POST /auth/register：注册（username, password, name, role=student）
- POST /auth/login：登录，返回 JWT token
- GET /auth/me：获取当前用户信息
密码用 bcrypt 哈希，JWT 过期时间从配置读取。
同时在 routers/admin/ 和 routers/student/ 的路由层加 JWT 依赖注入（先写占位，后续启用）。
```

### 知识图谱 CRUD API

```
在 server/app/routers/admin/ 下写知识图谱管理接口：
- GET /knowledge-points：分页查询 + 按章节筛选 + 按名称搜索
- GET /knowledge-points/{id}：单个详情（含前置/后继知识点）
- POST /knowledge-points：新增知识点
- PUT /knowledge-points/{id}：编辑
- DELETE /knowledge-points/{id}：删除前检查是否有其他知识点依赖它
- POST /knowledge-points/{id}/prerequisites：全量替换前置关系
同时写对应的 service 层，操作 Neo4j。
严格对照 docs/改进计划与任务卡/API契约文档-v2.md 的请求/响应格式。
```

### 题库管理 API

```
在 server/app/routers/admin/ 下写题库管理接口：
- 题目模型：id, content, type, difficulty, options(JSON), answer, explanation, knowledge_point_ids[]
- GET /questions：分页 + 按知识点/题型/难度/关键词筛选
- GET /questions/{id}：单个详情（含选项和解析）
- POST /questions：新增题目（含 Q矩阵关联写入 q_matrix 表）
- PUT /questions/{id}：编辑（同步更新 Q矩阵）
- DELETE /questions/{id}：删除（同步删除 Q矩阵关联）
- POST /questions/batch-import：批量导入，返回成功/失败统计
存 SQL Server，选项 JSON 列存储。
严格对照 docs/改进计划与任务卡/API契约文档-v2.md。
```

### 学员端知识点 API

```
在 server/app/routers/student/ 下写学员端知识点接口：
- GET /knowledge-points：学员视角列表（含每个知识点的 mastery_probability 和 status）
- GET /knowledge-points/{id}：详情（含前置知识点掌握状态 + 关联题目列表）
status 枚举：mastered(≥0.8) / learning(0.4-0.8) / weak(<0.4) / not_started
严格对照 docs/改进计划与任务卡/API契约文档-v2.md。
```

### 答题 API（单题 + 批量）

```
在 server/app/routers/student/ 下写答题接口：
- POST /submit-answer：提交单题答案
  入参：question_id, student_answer, time_spent
  出参：correct, correct_answer, explanation, mastery_change（知识点掌握概率变化）
- POST /submit-batch：批量提交
  入参：answers 数组（每项同 submit-answer）
  出参：每题的判题结果汇总
同时写 service 层：判题逻辑 + 更新 user_kp_mastery 表 + 写入 answer_records。
严格对照 docs/改进计划与任务卡/API契约文档-v2.md。
```

### DINA 认知诊断 Service

```
在 server/app/services/ 下实现 DINA 认知诊断：
1. Q矩阵管理：从 SQL Server q_matrix 表加载
2. EM算法估计题目参数（失误率 s、猜测率 g），参数从 config 读取
3. 贝叶斯后验推断学生知识掌握向量 α
4. POST /student/diagnosis：根据答题记录推断，结果写入 diagnosis_sessions 表
5. 同步更新 user_kp_mastery 表
纯 Python 实现，不依赖外部 ML 库。参考论文：de la Torre (2009) DINA model。
```

### 学习路径规划 Service

```
在 server/app/services/ 下实现学习路径推荐：
1. 从 Neo4j 加载知识点拓扑 + 前置关系
2. 拓扑排序确保前置关系不违反
3. 多指标贪心打分：距目标距离、当前掌握概率、难度、预估时长
4. GET /student/path：返回推荐学习序列，含每步的 reason 说明
5. GET /student/path/explain：调用大模型生成路径推荐的通俗解释
严格对照 docs/改进计划与任务卡/API契约文档-v2.md。
```

---

## Phase 3 · 前端核心 — 管理后台

> 每条指令写完一个完整页面（含 API 对接）。使用 Element Plus 组件。

### 管理后台 — 仪表盘

```
写 Vue 3 仪表盘页面 /dashboard：
- 4 个统计卡片：学生总数、题目总数、知识点总数、本周活跃学生
- 最近诊断概览表格（学生名、诊断时间、掌握率）
- 卡片数据从 API 获取，页面加载时调用
使用 Element Plus 的 el-row/el-col/el-card/el-table。
```

### 管理后台 — 知识图谱管理页

```
写 Vue 3 页面 /knowledge-graph：
- 左侧章节树（el-tree），点击筛选右侧知识点
- 右侧知识点表格（el-table）：名称、难度、时长、前置数、操作
- 新增/编辑知识点：el-dialog 表单，含名称、描述、难度滑块、预估时长
- 前置关系管理：点击知识点行 → 弹出前置关系设置（多选穿梭框）
API 对接到 /api/admin/knowledge-points/*
```

### 管理后台 — 题库管理页

```
写 Vue 3 页面 /questions：
- 顶部筛选栏：知识点选择器（el-select）、题型下拉、难度滑块、关键词搜索
- 题目表格（分页）：#、内容摘要、题型、难度、关联知识点、操作
- 新增/编辑：el-dialog 全屏弹窗
  - 题目内容 textarea、题型 radio-group（切换时重置选项）
  - 选项动态增减（单选 4 个、多选 4-6 个、判断固定对错）
  - 正确答案选择、解析 textarea、关联知识点多选
- 批量导入按钮：上传 Excel/JSON，调用 POST /questions/batch-import
API 对接到 /api/admin/questions/*
```

### 管理后台 — 学生数据页

```
写 Vue 3 页面 /students 和 /students/:id：
- /students：学生列表（分页 + 搜索），列：姓名、账号、答题数、掌握率、最近活跃、操作
- /students/:id：点击详情进入
  - 基本信息卡片
  - 知识点掌握雷达图（用 ECharts）
  - 答题历史时间线
  - α 向量进度条列表
API 对接到 /api/admin/students/*
```

### 管理后台 — 社交管理页

```
写 Vue 3 页面 /social：
- 成就定义列表（el-table）：名称、条件描述、图标、操作
- 新增/编辑成就：el-dialog 表单（名称、描述、图标选择、条件类型下拉、阈值）
- 打卡记录查询：日期范围选择器 + 学生筛选 + 结果表格
API 对接到 /api/admin/social/*
```

### 管理后台 — AI 报告页

```
写 Vue 3 页面 /ai-reports：
- 筛选栏：学生下拉选择 + 周起始日期选择器
- 周报列表表格：学生、周范围、答题数、正确率、操作
- 点击「查看」→ el-drawer 展开完整周报内容
  - 数据卡片（答题数/正确率/学习时长）
  - 新掌握知识点标签 + 薄弱知识点标签
  - AI 总结文本
API 对接到 /api/admin/ai-reports/*
```

### 管理后台 — 系统配置页

```
写 Vue 3 页面 /config：
- 表单分为两组：
  DINA 参数组：EM最大迭代、收敛阈值、s初始值、g初始值
  LLM 参数组：服务商下拉、模型名称、API Key（密码框）、超时秒数
- 保存按钮，调用 PUT /api/admin/config
- 页面加载时调用 GET /api/admin/config 回填
使用 el-form + el-card 分组布局。
```

---

## Phase 4 · 前端核心 — 客户端（UniApp）

> 每条指令写完一个完整页面。使用 uni-ui 组件，标签用 `<view>`/`<text>`。

### 客户端 — 首页

```
写 UniApp 首页 pages/index/index：
- 今日任务卡片：推荐学习的知识点名称 + 剩余待巩固数
- 连续打卡天数（大号数字高亮）
- 学习进度环（已掌握/总知识点，可用 canvas 或进度条）
- 快捷入口：开始学习、查看诊断、💬 AI答疑、本周周报（4 个图标按钮）
API: GET /api/student/knowledge-points（获取掌握统计）+ GET /api/student/social/check-in 状态
```

### 客户端 — 学习总览页

```
写 UniApp 页面 pages/learning/index：
- 按章节分组的折叠面板（展开/收起）
- 每个知识点行显示：名称、难度星标、掌握状态色标
  - 绿色 = mastered、黄色 = learning、红色 = weak、灰色 = not_started
- 点击知识点 → 跳转 pages/learning/detail
API: GET /api/student/knowledge-points
```

### 客户端 — 知识点详情页

```
写 UniApp 页面 pages/learning/detail：
- 知识点名称、描述、难度、预估时长
- 前置知识点列表（每个标注是否已掌握）
- 关联题目列表（标注是否已做过）
- 底部操作栏：「开始答题」主按钮 + 「🤖 问 AI」悬浮按钮
  - 点击「问AI」弹出半屏对话窗口，预注入当前知识点上下文
  - API: POST /api/student/chat/knowledge-point
  - 对话历史独立管理
API: GET /api/student/knowledge-points/{id}
```

### 客户端 — 学习路径页

```
写 UniApp 页面 pages/path/path：
- 顶部显示目标知识点
- 路径以时间轴/步骤条展示，每个节点：序号、知识点名、难度、预估时长、推荐原因
- 状态：已掌握（灰色+勾）、当前推荐（高亮）、待解锁（置灰）
- 点击节点 → 跳转知识点详情
API: GET /api/student/path + GET /api/student/path/explain（AI解释文字）
```

### 客户端 — 答题页

```
写 UniApp 页面 pages/quiz/quiz：
- 顶部进度条（第 n 题 / 共 m 题）
- 题目内容 + 选项列表
  - 单选：点击选项高亮，再点提交
  - 多选：勾选后点确认
  - 判断：对/错两个大按钮
- 提交后：显示对错图标 + 正确答案 + 解析文字
- 「下一题」按钮
- 全部完成后弹出小结（正确率 + 返回按钮）
API: POST /api/student/submit-answer（逐题）或 POST /api/student/submit-batch（批量）
先实现逐题模式。
```

### 客户端 — 诊断总览页

```
写 UniApp 页面 pages/diagnosis/index：
- 知识点掌握雷达图/进度条列表（各知识点 mastery_probability 可视化）
- AI 解读摘要文字
- 上次诊断时间
- 「重新诊断」按钮 → 调用 POST /api/student/diagnosis
- 「查看完整解读」→ 跳转 pages/diagnosis/explain
API: GET /api/student/knowledge-points（获取掌握数据）+ POST /api/student/diagnosis
```

### 客户端 — AI 解读页

```
写 UniApp 页面 pages/diagnosis/explain：
- 完整 AI 诊断评语（markdown 渲染）
- 优势知识点标签列表（绿色）
- 薄弱知识点标签列表（红色）
- 学习建议文字
API: POST /api/student/diagnosis/explain
```

### 客户端 — AI 答疑页（通用对话）

```
写 UniApp 页面 pages/chat/index：
- 聊天界面：消息气泡（用户右对齐蓝底、AI 左对齐灰底）
- 支持 markdown 渲染（数学公式等）
- 底部输入框 + 发送按钮
- AI 回答中显示「正在输入...」动画
- 关联知识点以卡片形式展示，点击跳转到知识点详情
- 对话历史存本地 uni.setStorageSync，切换页不丢失
- 从首页「💬 AI答疑」快捷入口跳转进入
API: POST /api/student/chat
```

### 客户端 — 社交首页

```
写 UniApp 页面 pages/social/index：
- 排行榜类型切换（周榜/月榜/总榜），默认周榜
- 排行榜列表：排名、头像占位、姓名、分数
- 自己的排名高亮显示
- 顶部「打卡」按钮 → POST /api/student/social/check-in
- 打卡成功提示 + 连续天数
- 「我的成就」入口 → 跳转 pages/social/achievements
API: GET /api/student/social/leaderboard + POST /api/student/social/check-in
```

### 客户端 — 成就列表页

```
写 UniApp 页面 pages/social/achievements：
- 成就卡片列表：
  - 已解锁：彩色图标 + 名称 + 解锁时间
  - 未解锁：灰色图标 + 进度条（如 15/20）
API: GET /api/student/social/achievements
```

### 客户端 — 我的页面

```
写 UniApp 页面 pages/mine/index：
- 头像 + 昵称 + 加入天数
- 成就入口（显示已解锁数量）
- 功能列表：历史周报、答题记录、设置
API: GET /auth/me
```

### 客户端 — 周报页

```
写 UniApp 页面 pages/report/report：
- 周范围显示（可左右切换周）
- 数据卡片：答题数、正确率、学习时长
- 新掌握知识点标签列表（绿色）
- 薄弱知识点标签列表（红色）
- AI 总结文字区域
API: GET /api/student/weekly-report?week_start=xxx
```

### 客户端 — 设置页

```
写 UniApp 页面 pages/settings/index：
- 修改昵称
- 修改密码（旧密码 + 新密码 + 确认）
- 退出登录
```

---

## Phase 5 · 高级功能 — 后端

### AI 诊断结果解读

```
在 server/app/services/ 下实现诊断结果解读：
- 输入：学生 α 向量（各知识点掌握概率）
- 调用大模型 API（DeepSeek/通义千问），生成诊断评语
- System Prompt：学生掌握了哪些（>0.8）、薄弱哪些（<0.4），给出学习建议
- 统一走 LLM 调用封装（超时 30s、重试 2 次、失败降级）
- 接口：POST /student/diagnosis/explain
- 返回：explanation 全文 + strengths 数组 + weaknesses 数组 + suggestion
```

### 学习周报生成

```
在 server/app/services/ 下实现周报生成：
- 输入：学生一周的答题记录、学习时长、掌握变化
- 统计：答题数、正确率、学习时长、新掌握知识点、仍薄弱知识点
- 调用大模型生成 AI 总结
- 接口：GET /student/weekly-report，结果写入 weekly_reports 表
- 如果该周已有报告则直接返回缓存
```

### AI 答疑 Service

```
在 server/app/services/ 下实现 AI 答疑对话：
1. 两个接口：
   - POST /student/chat：通用对话，系统 Prompt 注入学生当前学习概况
   - POST /student/chat/knowledge-point：知识点对话，注入知识点名称/描述/前置知识
2. 调用大模型 API，返回 markdown 格式回答
3. 对话记录由前端管理（history 入参），后端不持久化
4. 超时 30s + 重试 2 次，失败返回友好降级提示
5. 响应中附带关联知识点列表（从 Neo4j 关键词匹配或 LLM 输出中提取）
严格对照 docs/改进计划与任务卡/API契约文档-v2.md 的 3.7 节。
```

### 社交 API（排行榜/打卡/成就）

```
在 server/app/routers/student/ 下写社交接口：
- GET /social/leaderboard：排行榜
  参数 type(mastery/streak/points)、period(week/month/all)
  返回排名列表 + 我的排名
- POST /social/check-in：每日打卡
  同一天重复打卡返回已有记录，不报错
  自动计算连续打卡天数
- GET /social/achievements：我的成就列表
  遍历成就定义表，比对用户数据判断是否解锁
  返回已解锁 + 未解锁（含进度）的完整列表
同时在 routers/admin/ 下写管理端接口：
- GET/POST /admin/social/achievements：成就定义管理
- GET /admin/social/check-ins：打卡记录查询
严格对照 docs/改进计划与任务卡/API契约文档-v2.md。
```

---

## 审查 & 测试（随时用）

```
review 当前分支的所有改动，重点关注安全问题和逻辑错误
```

```
对 server/app/services/ 下的代码做安全审查，查注入、密钥泄露、权限问题
```

```
对 server/app/routers/ 下的代码做安全审查，查未授权访问、参数校验缺失
```

```
帮我写 server/tests/ 下的测试用例，覆盖知识图谱 CRUD 和 DINA 诊断的 service
```

```
帮我写 server/tests/ 下的测试用例，覆盖答题判题逻辑和 user_kp_mastery 更新
```

```
用 explore 分析 server/app/ 的模块结构，指出耦合问题和改进建议
```

---

## 使用方式

1. 让代理先读 `docs/AI开发总则.md`（项目宪法）
2. 再读 `docs/改进计划与任务卡/API契约文档-v2.md`（现行接口定义）、`docs/数据库设计.md`（表结构）
3. 复制上面某条指令粘贴发送
4. 代理完成后，审 diff，验收通过再继续下一条
5. 跨模块任务按依赖顺序：先数据库 → 后 API → 再前端页面
6. 每个 Phase 内部可以并行开多个会话（如管理后台 7 个页面可以同时写）
