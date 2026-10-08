# Reasonix API 契约文档 V2

> **现行唯一 API 规范。** 自 2026-10-04 起，新增接口、字段变更、权限变更和实现状态均以本文件为准。
> 旧文件 `docs/API契约文档.md` 冻结为 V1 历史快照，不再作为新开发依据。

## 0. 文档规则

### 0.1 契约优先级

1. 本文件；
2. `docs/AI开发总则.md`；
3. `docs/数据库设计.md`；
4. 历史 Delivery 文档和旧 V1 契约。

发生冲突时按以上顺序处理。任何接口变更必须先修改本文件并经 M0 确认，再修改后端和前端。

### 0.2 V2 兼容原则

- 尽量保留 V1 的路径、HTTP 方法和已有字段。
- 新增字段优先采用向后兼容方式；旧字段不得无迁移直接删除或改义。
- V2 主要新增：学生取题、学生/管理端图谱、仪表盘，以及诊断/路径可追踪字段。
- V2 收紧个性化数据权限：`/api/student/*` 均要求有效 student Token。
- 社交接口保留契约但标记为延期，不纳入当前核心闭环。

### 0.3 统一响应

```json
{
  "code": 0,
  "data": {},
  "message": ""
}
```

- `code = 0` 表示业务成功。
- 认证、权限和限流错误使用对应 HTTP 状态；其余已知业务错误沿用 HTTP 200 + 非零业务码。
- 未捕获异常统一返回 HTTP 500 + `code = 50000`，不得向客户端返回堆栈。

### 0.4 基础路径与认证

- 本地开发默认服务地址：`http://localhost:8000`，前端必须通过环境配置读取。
- 管理接口 `/api/admin/*`：必须携带有效 admin Token。
- 学生接口 `/api/student/*`：必须携带有效 student Token。
- `/auth/register`、`/auth/login`、`/health`：无需 Token。
- Header：`Authorization: Bearer <token>`。
- admin Token 访问 student 接口、student Token 访问 admin 接口均返回 HTTP 403 + `40101`。

### 0.5 分页、时间和空值

- `page` 从 1 开始，默认 1。
- `page_size` 默认 20，范围 1～100。
- 分页响应统一包含 `list`、`total`、`page`、`page_size`。
- 时间采用 ISO 8601，例如 `2026-10-04T14:30:00`。
- 日期采用 `YYYY-MM-DD`。
- “无数据”使用 JSON `null`，不得用空字符串或 `-1` 代替。

### 0.6 业务码

| code | HTTP | 含义 |
|---:|:---:|---|
| 0 | 200 | 成功 |
| 40000 | 422 | Pydantic 参数校验失败 |
| 40001 | 200 | 知识点被依赖，无法删除 |
| 40002 | 200 | 答题/Q 矩阵数据不足，无法诊断 |
| 40003 | 200 | 图谱查询范围或关系不合法 |
| 40100 | 401 | 未登录、凭证无效或登录过期 |
| 40101 | 403 | 角色或资源权限不足 |
| 40400 | 200 | 资源不存在 |
| 40900 | 200 | 资源冲突，如用户名重复 |
| 40901 | 429 | 请求过于频繁 |
| 40902 | 200 | 重复提交或幂等冲突 |
| 50000 | 500 | 未捕获服务端异常 |
| 50001 | 200 | SQL Server 异常 |
| 50002 | 200 | Neo4j 异常 |
| 60000 | 200 | LLM 服务异常，且无可用降级内容 |
| 60001 | 200 | LLM 超时，且无可用降级内容 |
| 60002 | 200 | LLM 返回结构异常，且无可用降级内容 |

LLM 功能原则上应提供规则降级；有降级内容时仍返回 `code=0`，并在 data 中标记 `degraded=true`。

---

## 1. 通用认证与健康检查

### 1.1 POST `/auth/register`

仅允许注册学生账号。

请求：

```json
{
  "username": "zhangsan",
  "password": "123456",
  "name": "张三",
  "role": "student"
}
```

约束：`username` 3～50 字符，`password` 至少 6 字符，`name` 1～50 字符；`role` 仅允许 `student`。

响应：

```json
{
  "code": 0,
  "data": {
    "user_id": "stu_a1b2c3d4",
    "username": "zhangsan",
    "name": "张三",
    "role": "student",
    "avatar": null,
    "created_at": "2026-10-04T10:00:00"
  },
  "message": "注册成功"
}
```

### 1.2 POST `/auth/login`

请求：

```json
{"username": "zhangsan", "password": "123456"}
```

响应：

```json
{
  "code": 0,
  "data": {
    "token": "eyJhbG...",
    "token_type": "Bearer",
    "expires_in": 86400
  },
  "message": "登录成功"
}
```

用户名或密码错误、账号禁用返回 40100；限流返回 40901。

### 1.3 GET `/auth/me`

需要任一有效 Token。

```json
{
  "code": 0,
  "data": {
    "user_id": "stu_a1b2c3d4",
    "username": "zhangsan",
    "name": "张三",
    "role": "student",
    "avatar": null,
    "created_at": "2026-10-04T10:00:00",
    "last_login_at": "2026-10-04T10:05:00"
  },
  "message": "获取成功"
}
```

### 1.4 GET `/health`

```json
{
  "code": 0,
  "data": {"status": "ok", "neo4j": true, "sqlserver": true},
  "message": ""
}
```

---

## 2. 管理端 API

## 2.1 知识点管理

### GET `/api/admin/knowledge-points`

参数：`page`、`page_size`、`chapter_id?`、`keyword?`。

列表项：

```json
{
  "id": "kp_001",
  "name": "一元一次方程",
  "description": "知识点描述",
  "chapter_id": "ch_01",
  "chapter_name": "方程",
  "difficulty": 0.3,
  "estimated_time": 25,
  "prerequisite_count": 2,
  "question_count": 5,
  "created_at": "2026-10-04T10:00:00"
}
```

### GET `/api/admin/knowledge-points/{id}`

在列表项基础上增加：

```json
{
  "prerequisites": [{"id": "kp_000", "name": "前置知识点"}],
  "dependents": [{"id": "kp_002", "name": "后继知识点"}]
}
```

### POST `/api/admin/knowledge-points`

```json
{
  "name": "一元一次方程",
  "description": "知识点描述",
  "chapter_id": "ch_01",
  "difficulty": 0.3,
  "estimated_time": 25,
  "prerequisite_ids": ["kp_000", "kp_003"]
}
```

`prerequisite_ids` 为可选字段；提供时，知识点字段和前置关系必须在同一 Neo4j 事务中完成全量替换。缺失时保持原有“只写知识点字段”的兼容行为；独立的前置关系接口继续保留。

响应 `data` 为创建后的知识点对象。

### PUT `/api/admin/knowledge-points/{id}`

请求字段同 POST；提供 `prerequisite_ids` 时与知识点字段在同一 Neo4j 事务中更新；响应 `data` 为更新后对象。

### DELETE `/api/admin/knowledge-points/{id}`

成功时 `data=null`；存在后继依赖时返回 40001。

### POST `/api/admin/knowledge-points/{id}/prerequisites`

全量替换前置关系：

```json
{"prerequisite_ids": ["kp_000", "kp_003"]}
```

保存前必须检查自依赖和环路；不合法返回 40003。

## 2.2 题库管理

### GET `/api/admin/questions`

参数：`page`、`page_size`、`knowledge_point_id?`、`type?`、`difficulty_min?`、`difficulty_max?`、`keyword?`。

`difficulty_min`/`difficulty_max` 范围 0～1，可单独传；min > max 返回 40000。

列表项：

```json
{
  "id": "q_001",
  "content": "题干",
  "type": "single_choice",
  "difficulty": 0.3,
  "knowledge_point_ids": ["kp_001"],
  "knowledge_point_names": ["一元一次方程"],
  "created_at": "2026-10-04T10:00:00"
}
```

### GET `/api/admin/questions/{id}`

```json
{
  "code": 0,
  "data": {
    "id": "q_001",
    "content": "题干",
    "type": "single_choice",
    "difficulty": 0.3,
    "options": [
      {"label": "A", "content": "选项 A"},
      {"label": "B", "content": "选项 B"}
    ],
    "answer": "B",
    "explanation": "解析",
    "knowledge_point_ids": ["kp_001"],
    "created_at": "2026-10-04T10:00:00"
  },
  "message": ""
}
```

### POST `/api/admin/questions`

```json
{
  "content": "题干",
  "type": "single_choice",
  "difficulty": 0.3,
  "options": [
    {"label": "A", "content": "选项 A"},
    {"label": "B", "content": "选项 B"}
  ],
  "answer": "B",
  "explanation": "解析",
  "knowledge_point_ids": ["kp_001"]
}
```

- `type`：`single_choice` / `multi_choice` / `true_false`。
- 多选答案使用排序后的 label 数组；服务端负责规范化。
- 至少关联一个知识点；写题目和 Q 矩阵必须在同一事务完成。

### PUT `/api/admin/questions/{id}`

请求同 POST；题目与 Q 矩阵在同一事务更新。

### DELETE `/api/admin/questions/{id}`

题目与 Q 矩阵关联在同一事务删除。

### POST `/api/admin/questions/batch-import`

请求：

```json
{"questions": []}
```

其中每项结构同单题 POST。

响应：

```json
{
  "code": 0,
  "data": {
    "success_count": 45,
    "fail_count": 2,
    "errors": [
      {"row": 12, "message": "选项不能为空"},
      {"row": 23, "message": "关联知识点不存在"}
    ]
  },
  "message": ""
}
```

## 2.3 管理端图谱（V2 新增）

### GET `/api/admin/graph`

参数：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| chapter_id | string? | null | 按章节过滤 |
| keyword | string? | null | 聚焦匹配知识点 |
| focus_id | string? | null | 聚焦节点 |
| depth | int | 2 | 0～3 |
| max_nodes | int | 200 | 1～500 |

响应使用第 4 章统一 GraphData，但管理接口中的学生字段均为 null。

首版不保存前端布局坐标；关系编辑继续使用 2.1 的 prerequisites 接口。

## 2.4 仪表盘（V2 新增）

### GET `/api/admin/dashboard/summary`

```json
{
  "code": 0,
  "data": {
    "student_count": 80,
    "question_count": 200,
    "knowledge_point_count": 22,
    "weekly_active_students": 35,
    "recent_diagnoses": [
      {
        "student_id": "stu_001",
        "student_name": "张三",
        "diagnosed_at": "2026-10-04T10:00:00",
        "average_mastery": 0.72
      }
    ]
  },
  "message": ""
}
```

活跃学生定义：指定统计周内存在答题、诊断或学习记录的去重学生数；实现时需在本文件变更记录中注明实际采用的数据源。

## 2.5 学生数据

### GET `/api/admin/students`

参数：`page`、`page_size`、`keyword?`。

```json
{
  "student_id": "stu_001",
  "username": "zhangsan",
  "name": "张三",
  "total_questions_done": 120,
  "mastered_kp_count": 15,
  "total_kp_count": 22,
  "average_mastery": 0.72,
  "last_active": "2026-10-04T18:30:00",
  "created_at": "2026-01-10T09:00:00"
}
```

### GET `/api/admin/students/{student_id}`

```json
{
  "code": 0,
  "data": {
    "student_id": "stu_001",
    "username": "zhangsan",
    "name": "张三",
    "alpha_vector": {"kp_001": 0.92, "kp_002": 0.45},
    "last_diagnosis": {
      "diagnosed_at": "2026-10-04T18:30:00",
      "algorithm_version": "dina-v1",
      "converged": true,
      "iterations": 28
    },
    "learning_history": [
      {
        "knowledge_point_id": "kp_001",
        "knowledge_point_name": "一元一次方程",
        "questions_done": 8,
        "correct_rate": 0.75,
        "mastery_probability": 0.92
      }
    ],
    "answer_history": [],
    "recommended_path": []
  },
  "message": ""
}
```

`answer_history` 和 `recommended_path` 可分页或限制最近数量，但必须在响应 meta 中说明限制。

## 2.6 AI 报告

### GET `/api/admin/ai-reports/weekly`

参数：`page`、`page_size`、`student_id?`、`week_start?`。

列表项包含学生、周范围、答题数、正确率、学习时长、生成时间和 `degraded`。

M9：列表仅列出已生成的周报，按周、学生筛选，返回标准分页。每项增加
`report_id`、`student_id`、`student_name`，并包含学生周报的全部字段，供抽屉查看；
读取时按下面的缓存策略复核统计，不展示过期缓存。仅管理员可访问。
列表读取不触发批量模型调用；缓存失效时当次显示最新统计和规则总结，学生读取时再生成并保存模型总结。

## 2.7 系统配置

### GET `/api/admin/config`

```json
{
  "code": 0,
  "data": {
    "dina_em_max_iterations": 500,
    "dina_em_convergence_threshold": 0.001,
    "dina_s_initial": 0.2,
    "dina_g_initial": 0.2,
    "path_weight_mastery": 0.4,
    "path_weight_target_distance": 0.3,
    "path_weight_difficulty": 0.2,
    "path_weight_time_cost": 0.1,
    "path_weight_profile": "default-v1",
    "llm_provider": "deepseek",
    "llm_model": "deepseek-chat",
    "llm_timeout": 30,
    "llm_api_key_configured": true,
    "llm_api_key_masked": "******abcd"
  },
  "message": ""
}
```

### PUT `/api/admin/config`

允许更新 GET 中的非派生字段；可选 `llm_api_key` 用于替换密钥。`llm_api_key` 为空或缺失表示不修改，响应永不返回原始密钥。

所有权重范围 0～1，总和必须为 1（允许浮点误差 0.0001），否则返回 40000。更新采用原子语义：服务端先校验完整候选配置及安全响应模型，再写入运行时配置；任一字段失败时，其他合法字段也不会生效。

可更新的非密钥字段显式传 `null` 时返回 `code=40000`，不会改变当前配置；字段省略表示保持原值。`llm_api_key` 的 `null`、空串或省略均表示不修改，非空值才替换密钥。失败后的 `GET /api/admin/config` 仍应正常返回原完整安全快照。

## 2.8 社交管理（延期）

以下路径保留，不纳入当前核心验收：

- `GET /api/admin/social/achievements`
- `POST /api/admin/social/achievements`
- `GET /api/admin/social/check-ins`

后续恢复开发前必须在本文件补齐完整响应模型。

---

## 3. 学生端 API

## 3.1 知识点

### GET `/api/student/knowledge-points`

```json
{
  "code": 0,
  "data": {
    "list": [
      {
        "id": "kp_001",
        "name": "一元一次方程",
        "chapter_id": "ch_01",
        "chapter_name": "方程",
        "difficulty": 0.3,
        "estimated_time": 25,
        "mastery_probability": 0.92,
        "status": "mastered"
      }
    ]
  },
  "message": ""
}
```

`status`：`mastered`（≥0.8）、`learning`（0.4～0.8）、`weak`（<0.4）、`not_started`（无数据）。边界 0.8 属于 mastered，0.4 属于 learning。

### GET `/api/student/knowledge-points/{id}`

```json
{
  "code": 0,
  "data": {
    "id": "kp_001",
    "name": "一元一次方程",
    "description": "知识点描述",
    "difficulty": 0.3,
    "estimated_time": 25,
    "mastery_probability": 0.92,
    "status": "mastered",
    "locked": false,
    "prerequisites": [
      {"id": "kp_000", "name": "前置知识", "mastered": true}
    ],
    "questions": [
      {
        "id": "q_001",
        "content": "题干",
        "type": "single_choice",
        "difficulty": 0.3,
        "done": false
      }
    ]
  },
  "message": ""
}
```

详情中的 `questions` 只用于摘要，不包含 options、答案和解析；正式答题通过 3.2 取题。

## 3.2 学生取题（V2 新增）

### GET `/api/student/questions`

参数：

| 参数 | 类型 | 必填 | 约束 |
|---|---|:---:|---|
| knowledge_point_id | string | 是 | 已存在知识点 |
| count | int | 否 | 默认 10，1～50 |
| exclude_done | bool | 否 | 默认 false |
| type | string | 否 | 三种题型之一 |

```json
{
  "code": 0,
  "data": {
    "list": [
      {
        "id": "q_001",
        "content": "题干",
        "type": "single_choice",
        "difficulty": 0.3,
        "options": [
          {"label": "A", "content": "选项 A"},
          {"label": "B", "content": "选项 B"}
        ]
      }
    ],
    "total": 1
  },
  "message": ""
}
```

禁止返回 `answer`、`correct_answer`、`explanation`。无 Q 矩阵或已下线题目不进入列表。

取题响应是学生专用安全视图，与管理端题目详情模型分离；`total` 是满足筛选条件的题目总数，`list` 最多返回 `count` 道。知识点存在但没有可用题目时返回 `code=0`、空 `list` 和 `total=0`，不视为异常。

## 3.3 答题

### POST `/api/student/submit-answer`

`student_answer`：单选/判断题为 string，多选题优先使用 string 数组；为兼容已发布客户端，也接受逗号分隔的 string。服务端统一去除首尾空白并按不区分大小写的 label 比较；多选比较前按 label 排序，但重复 label、空 label、未出现在题目 options 中的非法 label 均判错，不得通过集合去重或忽略非法项变成正确。判断题兼容 `true/false` 与展示文案 `对/错`。响应中的 `correct_answer` 类型与对应题型一致：单选/判断为 string，多选为按 label 排序后的 string 数组。

服务端会把规范化后的学生答案写入 `answer_records`；规范化只去除空白、统一大小写和多选的分隔表示，不删除重复或非法 label，以保留真实作答证据。

```json
{
  "question_id": "q_001",
  "student_answer": "B",
  "time_spent": 45
}
```

响应：

```json
{
  "code": 0,
  "data": {
    "correct": true,
    "correct_answer": "B",
    "explanation": "解析",
    "mastery_change": {
      "kp_001": {"before": 0.88, "after": 0.92}
    }
  },
  "message": "提交成功"
}
```

### POST `/api/student/submit-batch`

```json
{
  "answers": [
    {"question_id": "q_001", "student_answer": "B", "time_spent": 45}
  ]
}
```

响应：

```json
{
  "code": 0,
  "data": {
    "results": [
      {
        "question_id": "q_001",
        "correct": true,
        "correct_answer": "B",
        "explanation": "解析",
        "mastery_change": {"kp_001": {"before": 0.88, "after": 0.92}},
        "error": null
      }
    ],
    "summary": {
      "total": 1,
      "correct_count": 1,
      "wrong_count": 0,
      "fail_count": 0,
      "correct_rate": 1.0
    }
  },
  "message": "批量判题完成"
}
```

- results 顺序与 answers 一致。
- 单题业务失败写入 `error`，不阻塞其他题。
- 数据库异常整体回滚，返回 50001。
- `correct_rate = correct_count / (total - fail_count)`；无有效题时为 0。
- 单题提交和批量提交均按“每次服务端收到的有效提交都是一次 attempt”记录；允许学生重做同一道题，重做会新增 `answer_records`，并以该次作答结果链式更新当前 `user_kp_mastery` 快照，诊断默认使用全部记录并由诊断策略决定取数范围。
- 学生端提交按钮在请求进行中必须禁用，并且服务端返回前不得展示判题结果；服务端成功返回后才允许进入下一题。这样可阻止同一页面的重复点击造成重复提交；网络失败不写入结果状态，学生可安全重试。当前 V2 不把“重做”当作幂等冲突，也不以题目 ID 做唯一约束。
- 提交成功后，客户端必须刷新当前知识点详情和学习路径的掌握度/状态；本接口不承诺客户端缓存自动失效，页面需在回到前台或收到状态失效事件后重新请求数据。

## 3.4 DINA 诊断

### GET `/api/student/diagnosis`

读取当前学生最近一次诊断结果，供学生端恢复诊断页状态。尚未成功诊断时
返回 `code=0`、`data=null`，不视为异常。

响应 `data` 使用下方 POST 接口的 `DiagnosisResult` 结构；历史数据库记录
可能没有 `trace`，此时客户端只展示已有的 α 向量和诊断时间。

### POST `/api/student/diagnosis`

请求体为空。

```json
{
  "code": 0,
  "data": {
    "alpha_vector": {"kp_001": 0.92, "kp_002": 0.45},
    "diagnosed_at": "2026-10-04T18:30:00",
    "trace": {
      "algorithm_version": "dina-v1",
      "parameter_version": "default-v1",
      "answer_count": 35,
      "answer_time_from": "2026-09-01T00:00:00",
      "answer_time_to": "2026-10-04T18:29:59",
      "repeat_strategy": "latest_attempt",
      "converged": true,
      "iterations": 28
    }
  },
  "message": "诊断完成"
}
```

`trace` 为 V2 新增字段。本项目 M7 固定重复作答策略为 `latest_attempt`：
同一学生同一题按 `created_at` 最新的一次作为 DINA 观测，时间相同时按
`answer_records.id` 较大者；历史尝试仍保留，并继续计入知识点的
`questions_done` / `correct_count`。诊断只查询当前学生的必要字段，EM
初值与在线答题掌握度更新均来自同一组 DINA 配置项。

### POST `/api/student/diagnosis/explain`

```json
{
  "code": 0,
  "data": {
    "explanation": "诊断解读",
    "strengths": ["一元一次方程"],
    "weaknesses": ["含参方程"],
    "suggestion": "先巩固前置知识",
    "degraded": false,
    "degraded_reason": null
  },
  "message": ""
}
```

## 3.5 学生图谱（V2 新增）

### GET `/api/student/graph`

参数：

| 参数 | 类型 | 默认 | 约束 |
|---|---|---|---|
| view | string | personalized | tree / network / personalized |
| focus_id | string? | null | 知识点 ID |
| depth | int | 2 | 0～3 |
| max_nodes | int | 80 | 1～500 |
| include_mastered | bool | true | 是否包含已掌握节点 |

响应使用第 4 章 GraphData。

### GET `/api/student/graph/{id}/neighbors`

参数：`direction=both|incoming|outgoing`、`depth=1..2`、`max_nodes=1..100`。

响应使用 GraphData；focus 不存在返回 40400。

## 3.6 学习路径

### GET `/api/student/path`

参数：`target_kp_id?`、`count=5`（1～50）。

```json
{
  "code": 0,
  "data": {
    "target": {"id": "kp_005", "name": "目标知识点"},
    "steps": [
      {
        "order": 1,
        "knowledge_point": {"id": "kp_002", "name": "前置知识点"},
        "reason": "当前掌握不足且是目标前置知识",
        "difficulty": 0.5,
        "estimated_time": 30,
        "mastery_probability": 0.45,
        "status": "learning",
        "locked": false,
        "reason_codes": ["LOW_MASTERY", "TARGET_PREREQUISITE"],
        "score_components": {
          "mastery": 0.38,
          "target_distance": 0.25,
          "difficulty": 0.18,
          "time_cost": 0.10,
          "total": 0.91
        }
      }
    ],
    "meta": {
      "algorithm_version": "greedy-v1",
      "weight_profile": "default-v1",
      "degraded": false,
      "degraded_reason": null
    }
  },
  "message": ""
}
```

V1 字段全部保留；`status`、`locked`、`reason_codes`、`score_components`、`meta` 为 V2 新增。

### GET `/api/student/path/explain`

参数与 path 一致。

```json
{
  "code": 0,
  "data": {
    "explanation": "路径解释",
    "degraded": false,
    "degraded_reason": null
  },
  "message": ""
}
```

## 3.7 AI 答疑

### POST `/api/student/chat`

```json
{
  "message": "配方法和公式法有什么区别？",
  "history": [
    {"role": "user", "content": "上一轮问题"},
    {"role": "assistant", "content": "上一轮回答"}
  ]
}
```

- `message` 1～2000 字符。
- `history` 最多 20 条/10 轮，role 仅允许 user/assistant。
- 每条历史 content 为 1～2000 字符；空白输入拒绝。客户端按学生 ID 和知识点 ID
  隔离保存最近十轮成功对话，欢迎语、网络错误不进入 history。
- 关联知识点由服务端图谱核实；模型不能创建知识点或修改学习数据。

响应：

```json
{
  "code": 0,
  "data": {
    "reply": "回答",
    "related_knowledge_points": [
      {"id": "kp_002", "name": "配方法"}
    ],
    "degraded": false,
    "degraded_reason": null
  },
  "message": ""
}
```

### POST `/api/student/chat/knowledge-point`

```json
{
  "message": "为什么先移项？",
  "knowledge_point_id": "kp_002",
  "history": []
}
```

响应字段同 chat，并增加 `knowledge_point_name`。

## 3.8 周报

### GET `/api/student/weekly-report`

参数：`week_start?`，不传取本周一。

```json
{
  "code": 0,
  "data": {
    "week_start": "2026-09-28",
    "week_end": "2026-10-04",
    "questions_done": 35,
    "correct_rate": 0.72,
    "study_time_minutes": 240,
    "new_mastered": [{"id": "kp_002", "name": "配方法"}],
    "still_weak": [{"id": "kp_003", "name": "求根公式"}],
    "ai_summary": "周报总结",
    "generated_at": "2026-10-04T20:00:00",
    "cached": true,
    "degraded": false,
    "degraded_reason": null
  },
  "message": ""
}
```

统计字段必须由数据库计算；LLM 只生成 `ai_summary`。

M9 统计和缓存口径：`week_start` 必须为非未来的周一（日期格式 YYYY-MM-DD）。
答题数统计该周所有尝试（含重复），正确率为正确次数/尝试数，无作答为 0；
学习时长仅计答题记录 time_spent 的非负秒数，合计向下取整为分钟。
掌握变化以存储的 DINA 诊断快照为历史依据：周前最后一份快照与周内快照比较，
本周再纳入当前掌握快照；`new_mastered` 是周前未掌握、本周首次跨过 0.8 且周末仍掌握的知识点，
首次记录前视为未开始；`still_weak` 是周末最后已记录概率小于 0.4 的知识点。
历史周缺少诊断快照时不根据当前掌握度反推历史，不虚构掌握变化。
服务端持久化同学生同周缓存；每次读取复核真实统计、诊断/掌握快照和知识名称摘要，
数据或模型配置变化立即失效。成功总结最多缓存 24 小时，降级总结缓存 60 秒后重试；
缓存命中保持 generated_at，返回 cached=true。API Key 不写入报告或日志。
诊断解读只解释最近一次诊断，无诊断时返回明确的规则学习建议。

## 3.9 社交（延期）

保留以下 V1 路径，不纳入当前核心验收：

- `GET /api/student/social/leaderboard`
- `POST /api/student/social/check-in`
- `GET /api/student/social/achievements`

后续恢复开发前必须补齐权限、分页和完整错误语义。

---

## 4. 统一图谱模型 GraphData

```json
{
  "nodes": [
    {
      "id": "kp_001",
      "label": "一元一次方程",
      "node_type": "knowledge_point",
      "chapter_id": "ch_01",
      "difficulty": 0.3,
      "estimated_time": 25,
      "mastery_probability": 0.62,
      "status": "learning",
      "locked": false,
      "recommend_order": 2,
      "reason": "目标知识点的前置知识",
      "tags": ["重点"]
    }
  ],
  "edges": [
    {
      "id": "pre_kp_001_kp_002",
      "source": "kp_001",
      "target": "kp_002",
      "relation": "prerequisite",
      "directed": true,
      "recommended": true
    }
  ],
  "meta": {
    "view": "personalized",
    "focus_id": "kp_001",
    "total_nodes": 22,
    "returned_nodes": 22,
    "truncated": false,
    "layout_hint": "dagre",
    "algorithm_version": "greedy-v1",
    "weight_profile": "default-v1"
  }
}
```

### 4.1 Node 约束

- `node_type`：`course` / `chapter` / `knowledge_point`。
- `status`：`mastered` / `learning` / `weak` / `not_started`；管理接口可为 null。
- `locked` 独立于 status；管理接口可为 null。
- `mastery_probability` 范围 0～1，无数据或管理接口为 null。
- `recommend_order` 不在当前推荐路径中为 null。
- `tags` 首版允许为空数组，不要求扩充当前数据。

### 4.2 Edge 约束

- `relation`：`belongs_to` / `prerequisite` / `recommended_next` / `related`。
- `recommended=true` 仅表示属于当前路径高亮，不改变 Neo4j 原关系。
- edge id 在单次响应内唯一且稳定。

### 4.3 Meta 约束

- `total_nodes` 是当前查询条件下完整结果数。
- `returned_nodes` 必须等于 nodes 数组长度。
- `truncated=true` 时前端必须提示正在展示局部图谱。
- 课程根节点可以由 service 生成，不要求写入 Neo4j。

---

## 5. 权限矩阵

| 接口组 | 未登录 | student | admin |
|---|:---:|:---:|:---:|
| `/auth/register`、`/auth/login`、`/health` | 允许 | 允许 | 允许 |
| `/auth/me` | 401 | 允许 | 允许 |
| `/api/student/*` | 401 | 允许 | 403 |
| `/api/admin/*` | 401 | 403 | 允许 |

学生只能读取和写入自己的答题、掌握度、诊断、路径、周报和聊天上下文。任何通过参数传入其他 student_id 的学生请求均返回 40101。

---

## 6. 实现状态与任务映射

状态说明：✅ 已实现；🛠 需按 V2 调整；🔲 未实现；⏸ 延期。

| 接口/模块 | 状态 | 任务 |
|---|:---:|---|
| `/auth/register`、`/auth/login`、`/auth/me` | ✅ | M1 |
| 管理知识点 CRUD | ✅ | M5 联调 |
| 管理题库 CRUD/批量导入 | ✅ | M5 联调 |
| `GET /api/admin/graph` | ✅ | M3 |
| `GET /api/admin/dashboard/summary` | ✅ | M6 |
| 管理学生列表/详情 | ✅ | M6 |
| 管理 AI 周报 | ✅ | M9 |
| 管理配置 | ✅ | M8/M10 |
| 学生知识点列表/详情 | ✅ | M1/M2 |
| `GET /api/student/questions` | ✅ | M2/M5-R3 |
| 学生单题/批量提交 | ✅ | M2 |
| DINA 诊断 | ✅ | M7 |
| DINA AI 解读 | ✅ | M9 |
| 学生图谱/邻居 | ✅ | M3 |
| 学习路径 | ✅ | M8 |
| 路径 AI 解释 | ✅ | M8/M9 |
| AI 答疑 | ✅ | M9 |
| 周报 | ✅ | M9 |
| 社交接口 | ⏸ | 后续任务 |

> 2026-10-07 收口说明：✅ 表示当前仓库已有对应后端路由、service、前端调用和测试/复验覆盖；⏸ 表示按范围决策延期。API 状态为实现状态，不替代 M0 对真实数据、页面和全链路证据的最终裁决。

---

## 7. 契约变更流程

1. 执行者在本文件中提出变更，写明兼容性和影响模块。
2. M0 审核路径、权限、字段、错误码和迁移影响。
3. 契约合并后，才允许修改 models、service、router 和前端。
4. 实现完成后更新第 6 章状态，并在第 8 章追加记录。
5. 破坏性变更必须升 V3，不得在 V2 中无提示改义。

## 8. 变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-10-04 | 2.0.0-draft | 以 V1 为基础新建 V2；保留既有路径，新增学生取题、图谱、邻居、管理图谱和仪表盘；扩展诊断追踪和路径解释字段；统一学生接口鉴权。 |
| 2026-10-04 | 2.0.0-M3 | 定稿三条图谱接口：学生图谱与邻居接口强制 student Token，管理图谱强制 admin Token；统一使用 GraphData 的 node/edge/meta 结构；`max_nodes` 作用于返回节点数组并由 `meta.returned_nodes`、`meta.truncated` 准确反映；学生掌握度采用单次批量 SQL 查询，Neo4j/SQL Server 异常分别返回 50002/50001。 |
| 2026-10-04 | 2.0.0-M3-R1 | 在不改变 URL 和 GraphData 字段的前提下明确截断语义：focus 始终优先保留，邻居按 Neo4j 距离和稳定 ID 排序；Neo4j 负责候选计数、章节计数和有界选择；`include_mastered=false` 由用户已掌握 ID 排除后再计数；直接前置可在渲染窗口外参与 locked 与推荐约束。 |
| 2026-10-04 | 2.0.0-M10 | 按当前仓库实现收口 API 状态表；数据库迁移、安全启动、CI 和部署文档作为工程门禁，仍需 M0 最终联调证据。 |
| 2026-10-05 | 2.0.0-M2 | 冻结学生取题安全视图、三种题型答案规范化、多选重复/非法 label 判错；明确每次有效提交均记录为 attempt、重做更新掌握快照、批量数据库异常整体回滚，以及客户端提交中禁用并在成功后刷新知识点/路径状态。 |
| 2026-10-05 | 2.0.0-M7 | 定稿 DINA 重复作答策略为 `latest_attempt`；新增学生最近诊断 GET；POST 诊断 trace 返回算法/参数版本、答题范围、收敛状态和迭代次数；答题与掌握查询限定当前学生。 |
| 2026-10-06 | 2.0.0-M6 | 实现管理端仪表盘、学生分页/搜索和学生详情；仪表盘本周活跃学生按本周一以来 `answer_records` 与 `diagnosis_sessions` 的去重学生统计；详情中的答题与诊断历史分别限制最近 50/10 条，并在 `meta` 中返回限制口径。 |
| 2026-10-06 | 2.0.0-M8 | 实现路径权重运行时配置、权重 profile/算法版本追踪、步骤 `status`/`reason_codes`/`score_components` 与路径 `meta`；完整拓扑环路拒绝推荐；掌握数据源失败返回 `degraded=true`；管理配置接口只回显 API Key 掩码。 |
