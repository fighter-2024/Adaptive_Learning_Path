# API 契约文档

> **V1 历史快照（已冻结）**：自 2026-10-04 起，现行唯一规范为
> `docs/改进计划与任务卡/API契约文档-v2.md`。本文件仅用于追溯旧实现，不再追加新接口或字段。

> V1 原规则：接口变更先改契约再改代码。新开发请在 V2 中执行该流程。

---

## 通用规范

- 基础路径：`http://localhost:8000`
- 统一响应：`{"code": 0, "data": ..., "message": ""}`
- 认证凭证通过 Header `Authorization: Bearer <token>` 传递：
  - **管理后台接口（/api/admin，除 /health）**：必须携带管理员 Token，否则 HTTP 401（业务码 40100）；学生 Token 访问返回 HTTP 403（业务码 40101）
  - **学员端写接口**（submit-answer / submit-batch / diagnosis）：必须携带学生 Token，否则 401
  - **学员端读接口**（knowledge-points / path 等）：Token 可选；未携带时降级为匿名视角（无掌握数据）
- 认证接口（/auth/login、/auth/register）带速率限制：窗口内超过上限返回 HTTP 429（业务码 40901），详见 `.env.example` 的 `RATE_LIMIT_*` 配置
- 时间格式统一为 `2026-01-15T14:30:00`（ISO 8601，服务器本地时间）
- 分页参数：`page`（从 1 开始）、`page_size`（默认 20，最大 100）

> **示例数据说明**：本文档与 `server/sql/init.sql` 中的示例数据（如 `ch_01=一元二次方程`）仅用于接口示意，与真实演示数据不是同一套。实际导入 Neo4j 的演示数据以 `kg-data/data/knowledge_points/*.csv` 为准（其 `ch_01=一元一次方程`）。跨库引用（`q_matrix` / `user_kp_mastery` 的 `knowledge_point_id`）必须与 Neo4j 实际节点 ID 一致。

### 业务码对照表

| 业务码 | HTTP 状态 | 含义 |
|--------|-----------|------|
| `0` | 200 | 成功 |
| `40000` | 422 | 请求参数校验失败（Pydantic） |
| `40001` | 200 | 知识点被其他知识点依赖，无法删除（契约 1.1 专用码值） |
| `40002` | 200 | 答题记录不足（或 Q 矩阵无数据），无法诊断 |
| `40100` | 401 | 未登录 / 登录已过期 / 凭证无效 |
| `40101` | 403 | 无权访问（角色不符） |
| `40400` | 200 | 资源不存在 |
| `40900` | 200 | 资源冲突（如用户名已注册） |
| `40901` | 429 | 请求过于频繁（触发速率限制） |
| `50000` | 500 | 服务器内部错误（未捕获异常兜底） |
| `50001` | 200 | 数据库（SQL Server）异常 |
| `50002` | 200 | 图数据库（Neo4j）异常 |
| `60000` / `60001` / `60002` | 200 | 大模型服务异常 / 超时 / 返回异常（预留：当前 LLM 失败一律走降级内容，不抛这些码） |

> 说明：业务异常（40001/40002/40400/40900/50001/50002/6xxxx）以 HTTP 200 + 业务码返回；认证/限速类（40100/40101/40901）以对应 HTTP 状态码返回，响应体同为统一格式 `{code, data, message}`。

---

## 一、管理后台 API（/api/admin）

### 1.1 知识点管理

#### GET /api/admin/knowledge-points

查询知识点列表（分页 + 筛选）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| page | int | 否 | 页码，默认 1 |
| page_size | int | 否 | 每页条数，默认 20 |
| chapter_id | string | 否 | 按章节筛选 |
| keyword | string | 否 | 按名称模糊搜索 |

**响应**：
```json
{
    "code": 0,
    "data": {
        "list": [
            {
                "id": "kp_001",
                "name": "一元二次方程的定义",
                "description": "理解一元二次方程的标准形式 ax²+bx+c=0",
                "chapter_id": "ch_01",
                "chapter_name": "一元二次方程",
                "difficulty": 0.3,
                "estimated_time": 25,
                "prerequisite_count": 2,
                "question_count": 5,
                "created_at": "2026-01-15T10:00:00"
            }
        ],
        "total": 150,
        "page": 1,
        "page_size": 20
    },
    "message": ""
}
```

#### GET /api/admin/knowledge-points/{id}

查询单个知识点详情。

**响应**：
```json
{
    "code": 0,
    "data": {
        "id": "kp_001",
        "name": "一元二次方程的定义",
        "description": "理解一元二次方程的标准形式 ax²+bx+c=0",
        "chapter_id": "ch_01",
        "chapter_name": "一元二次方程",
        "difficulty": 0.3,
        "estimated_time": 25,
        "prerequisites": [
            {"id": "kp_000", "name": "一元一次方程"}
        ],
        "dependents": [
            {"id": "kp_002", "name": "配方法解一元二次方程"}
        ]
    },
    "message": ""
}
```

#### POST /api/admin/knowledge-points

新增知识点。

**请求体**：
```json
{
    "name": "一元二次方程的定义",
    "description": "理解一元二次方程的标准形式 ax²+bx+c=0",
    "chapter_id": "ch_01",
    "difficulty": 0.3,
    "estimated_time": 25
}
```

**响应**：`data` 返回创建后的知识点对象（含 id）。

#### PUT /api/admin/knowledge-points/{id}

编辑知识点。请求体同 POST。

#### DELETE /api/admin/knowledge-points/{id}

删除知识点。如有其他知识点依赖它，返回错误：
```json
{"code": 40001, "data": null, "message": "该知识点被 2 个知识点依赖，无法删除"}
```

#### POST /api/admin/knowledge-points/{id}/prerequisites

设置前置依赖。

**请求体**：
```json
{
    "prerequisite_ids": ["kp_000", "kp_003"]
}
```
全量替换（传什么就是什么），不追加。

---

### 1.2 题库管理

#### GET /api/admin/questions

查询题目列表。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| page | int | 否 | 页码 |
| page_size | int | 否 | 每页条数 |
| knowledge_point_id | string | 否 | 按关联知识点筛选 |
| type | string | 否 | single_choice / multi_choice / true_false |
| difficulty_min | float | 否 | 难度下限（含），按难度区间筛选，0.0~1.0 |
| difficulty_max | float | 否 | 难度上限（含），按难度区间筛选，0.0~1.0 |
| keyword | string | 否 | 按题目内容模糊搜索 |

> 难度筛选为闭区间 `[difficulty_min, difficulty_max]`（含边界），两个参数可单独使用（只传一个表示单边筛选）；`difficulty_min` 大于 `difficulty_max` 时返回参数校验错误。

**响应**：
```json
{
    "code": 0,
    "data": {
        "list": [
            {
                "id": "q_001",
                "content": "下列哪个是方程 x²-4=0 的解？",
                "type": "single_choice",
                "difficulty": 0.3,
                "knowledge_point_ids": ["kp_001"],
                "knowledge_point_names": ["一元二次方程的定义"],
                "created_at": "2026-01-15T10:00:00"
            }
        ],
        "total": 200,
        "page": 1,
        "page_size": 20
    },
    "message": ""
}
```

#### GET /api/admin/questions/{id}

查询单个题目详情。

**响应**：
```json
{
    "code": 0,
    "data": {
        "id": "q_001",
        "content": "下列哪个是方程 x²-4=0 的解？",
        "type": "single_choice",
        "difficulty": 0.3,
        "options": [
            {"label": "A", "content": "x=4"},
            {"label": "B", "content": "x=2"},
            {"label": "C", "content": "x=0"},
            {"label": "D", "content": "x=-4"}
        ],
        "answer": "B",
        "explanation": "x²-4=0 → x²=4 → x=±2，选项中 x=2 正确",
        "knowledge_point_ids": ["kp_001"],
        "created_at": "2026-01-15T10:00:00"
    },
    "message": ""
}
```

#### POST /api/admin/questions

新增题目。

**请求体**：
```json
{
    "content": "下列哪个是方程 x²-4=0 的解？",
    "type": "single_choice",
    "difficulty": 0.3,
    "options": [
        {"label": "A", "content": "x=4"},
        {"label": "B", "content": "x=2"},
        {"label": "C", "content": "x=0"},
        {"label": "D", "content": "x=-4"}
    ],
    "answer": "B",
    "explanation": "x²-4=0 → x²=4 → x=±2",
    "knowledge_point_ids": ["kp_001"]
}
```

#### PUT /api/admin/questions/{id}

编辑题目。请求体同 POST。

#### DELETE /api/admin/questions/{id}

删除题目。

#### POST /api/admin/questions/batch-import

批量导入题目（Excel/JSON）。

**请求体**：
```json
{
    "questions": [ /* 题目对象数组，结构同 POST 单个 */ ]
}
```

**响应**：
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

---

### 1.3 学生数据

#### GET /api/admin/students

学生列表。

**响应**：
```json
{
    "code": 0,
    "data": {
        "list": [
            {
                "student_id": "stu_001",
                "username": "zhangsan",
                "name": "张三",
                "total_questions_done": 120,
                "mastered_kp_count": 15,
                "total_kp_count": 50,
                "last_active": "2026-03-20T18:30:00",
                "created_at": "2026-01-10T09:00:00"
            }
        ],
        "total": 80,
        "page": 1,
        "page_size": 20
    },
    "message": ""
}
```

#### GET /api/admin/students/{student_id}

学生详情 + 诊断结果。

**响应**：
```json
{
    "code": 0,
    "data": {
        "student_id": "stu_001",
        "username": "zhangsan",
        "name": "张三",
        "alpha_vector": {
            "kp_001": 0.92,
            "kp_002": 0.78,
            "kp_003": 0.45
        },
        "learning_history": [
            {
                "knowledge_point_id": "kp_001",
                "knowledge_point_name": "一元二次方程的定义",
                "questions_done": 8,
                "correct_rate": 0.75,
                "mastery_probability": 0.92
            }
        ]
    },
    "message": ""
}
```

---

### 1.4 社交管理

#### GET /api/admin/social/achievements

成就列表管理。

#### POST /api/admin/social/achievements

新增成就定义。

**请求体**：
```json
{
    "name": "初出茅庐",
    "description": "完成首次诊断",
    "icon": "star",
    "condition_type": "first_diagnosis",
    "condition_value": "1"
}
```

#### GET /api/admin/social/check-ins

打卡记录管理（可按日期/学生筛选）。

---

### 1.5 AI 报告

#### GET /api/admin/ai-reports/weekly

批量查看学生周报。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| student_id | string | 否 | 按学生筛选 |
| week_start | string | 否 | 周起始日期，如 2026-03-16 |

---

### 1.6 系统配置

#### GET /api/admin/config

获取当前系统配置。

**响应**：
```json
{
    "code": 0,
    "data": {
        "dina_em_max_iterations": 500,
        "dina_em_convergence_threshold": 0.001,
        "dina_s_initial": 0.2,
        "dina_g_initial": 0.2,
        "llm_provider": "deepseek",
        "llm_model": "deepseek-chat",
        "llm_timeout": 30
    },
    "message": ""
}
```

#### PUT /api/admin/config

更新系统配置。请求体同 GET 的 data 结构。

---

## 二、学员端 API（/api/student）

### 2.1 学习

#### GET /api/student/knowledge-points

获取学员视角的知识点列表（含自己的掌握状态）。

**响应**：
```json
{
    "code": 0,
    "data": {
        "list": [
            {
                "id": "kp_001",
                "name": "一元二次方程的定义",
                "chapter_name": "一元二次方程",
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
status 枚举：`mastered`（≥0.8）、`learning`（0.4-0.8）、`weak`（<0.4）、`not_started`（无数据）。

> `mastery_probability` 字段说明：无掌握数据（未作答/未诊断/未登录）时该字段为 `null`，对应 `status = not_started`；其余情况为 0.0~1.0 的数字。前端需兼容 null。

#### GET /api/student/knowledge-points/{id}

知识点详情 + 关联题目。

**响应**：
```json
{
    "code": 0,
    "data": {
        "id": "kp_001",
        "name": "一元二次方程的定义",
        "description": "理解一元二次方程的标准形式 ax²+bx+c=0",
        "difficulty": 0.3,
        "estimated_time": 25,
        "mastery_probability": 0.92,
        "prerequisites": [
            {"id": "kp_000", "name": "一元一次方程", "mastered": true}
        ],
        "questions": [
            {
                "id": "q_001",
                "content": "下列哪个是方程 x²-4=0 的解？",
                "type": "single_choice",
                "difficulty": 0.3,
                "done": false
            }
        ]
    },
    "message": ""
}
```

---

### 2.2 答题

#### POST /api/student/submit-answer

提交一道题的答案。

**请求体**：
```json
{
    "question_id": "q_001",
    "student_answer": "B",
    "time_spent": 45
}
```

**响应**：
```json
{
    "code": 0,
    "data": {
        "correct": true,
        "correct_answer": "B",
        "explanation": "x²-4=0 → x²=4 → x=±2，选项中 x=2 正确",
        "mastery_change": {
            "kp_001": {"before": 0.88, "after": 0.92}
        }
    },
    "message": ""
}
```

#### POST /api/student/submit-batch

提交一批答案（做完一组题后一次性提交）。

**请求体**：
```json
{
    "answers": [
        {"question_id": "q_001", "student_answer": "B", "time_spent": 45},
        {"question_id": "q_002", "student_answer": "A", "time_spent": 30}
    ]
}
```

**响应**（2026-08-16 补记：本接口出参结构此前未定义，按「每题的判题结果汇总」语义定稿）：
```json
{
    "code": 0,
    "data": {
        "results": [
            {
                "question_id": "q_001",
                "correct": true,
                "correct_answer": "B",
                "explanation": "x²-4=0 → x²=4 → x=±2，选项中 x=2 正确",
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

- `results` 顺序与入参 `answers` 一致；判题失败（题目不存在/已下线）的项 `error` 给出原因，其余字段为 null，不阻塞其他题；
- `summary.correct_rate = correct_count / (total - fail_count)`，无有效判题时为 0.0；
- 全部成功项在同一事务写入 answer_records 与 user_kp_mastery，数据库异常整体回滚（业务码 50001）。

---

### 2.3 诊断

#### POST /api/student/diagnosis

触发 DINA 诊断（根据答题记录重新推断 α 向量）。

**响应**：
```json
{
    "code": 0,
    "data": {
        "alpha_vector": {
            "kp_001": 0.92,
            "kp_002": 0.78,
            "kp_003": 0.45
        },
        "diagnosed_at": "2026-03-20T18:30:00"
    },
    "message": ""
}
```

#### POST /api/student/diagnosis/explain

获取诊断结果 AI 解读。

**响应**：
```json
{
    "code": 0,
    "data": {
        "explanation": "同学你好！根据最近的答题情况，你在「一元二次方程的定义」上掌握得很好（92%），也基本掌握了「配方法」（78%），但「求根公式推导」还比较薄弱（45%）。建议你先巩固配方法，再尝试推导求根公式。",
        "strengths": ["一元二次方程的定义"],
        "weaknesses": ["求根公式推导"],
        "suggestion": "建议先复习 kp_002，再学习 kp_003"
    },
    "message": ""
}
```

---

### 2.4 学习路径

#### GET /api/student/path

获取推荐学习路径。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| target_kp_id | string | 否 | 目标知识点，不传则推荐全局下一步 |
| count | int | 否 | 推荐步数，默认 5 |

**响应**：
```json
{
    "code": 0,
    "data": {
        "target": {"id": "kp_005", "name": "求根公式应用"},
        "steps": [
            {
                "order": 1,
                "knowledge_point": {"id": "kp_002", "name": "配方法解一元二次方程"},
                "reason": "当前掌握 78%，巩固后可进入下一阶段",
                "difficulty": 0.5,
                "estimated_time": 30,
                "mastery_probability": 0.78
            },
            {
                "order": 2,
                "knowledge_point": {"id": "kp_003", "name": "求根公式推导"},
                "reason": "前置知识尚未完全掌握，需重点学习",
                "difficulty": 0.6,
                "estimated_time": 40,
                "mastery_probability": 0.45
            }
        ]
    },
    "message": ""
}
```

#### GET /api/student/path/explain

获取路径推荐的 AI 解释。

**响应**：
```json
{
    "code": 0,
    "data": {
        "explanation": "根据你的诊断结果，接下来建议先花 30 分钟巩固「配方法」，这是推导求根公式的前置知识。然后再挑战更高难度的「求根公式推导」。这样安排可以避免直接跳级造成挫败感。"
    },
    "message": ""
}
```

---

### 2.5 社交

#### GET /api/student/social/leaderboard

排行榜。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| type | string | 否 | mastery（掌握率）/ streak（连续打卡）/ points（积分），默认 mastery |
| period | string | 否 | week / month / all，默认 week |

**响应**：
```json
{
    "code": 0,
    "data": {
        "list": [
            {
                "rank": 1,
                "student_name": "张三",
                "avatar": "",
                "score": 0.85,
                "is_me": false
            },
            {
                "rank": 2,
                "student_name": "我",
                "avatar": "",
                "score": 0.72,
                "is_me": true
            }
        ],
        "my_rank": 2
    },
    "message": ""
}
```

#### POST /api/student/social/check-in

每日打卡。

**响应**：
```json
{
    "code": 0,
    "data": {
        "streak_days": 7,
        "checked_in": true
    },
    "message": "打卡成功，已连续打卡 7 天！"
}
```

#### GET /api/student/social/achievements

我的成就列表。

**响应**：
```json
{
    "code": 0,
    "data": {
        "achievements": [
            {
                "id": "ach_001",
                "name": "初出茅庐",
                "description": "完成首次诊断",
                "icon": "star",
                "unlocked_at": "2026-03-15T10:00:00",
                "unlocked": true
            },
            {
                "id": "ach_002",
                "name": "知识达人",
                "description": "掌握 20 个知识点",
                "icon": "trophy",
                "unlocked": false,
                "progress": "15/20"
            }
        ]
    },
    "message": ""
}
```

---

### 2.6 周报

#### GET /api/student/weekly-report

获取本周/指定周的学习报告。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| week_start | string | 否 | 周起始日期，不传默认本周一 |

**响应**：
```json
{
    "code": 0,
    "data": {
        "week_start": "2026-03-16",
        "week_end": "2026-03-22",
        "questions_done": 35,
        "correct_rate": 0.72,
        "study_time_minutes": 240,
        "new_mastered": [
            {"id": "kp_002", "name": "配方法解一元二次方程"}
        ],
        "still_weak": [
            {"id": "kp_003", "name": "求根公式推导"}
        ],
        "ai_summary": "本周你完成了 35 道题，正确率 72%，累计学习 4 小时。成功掌握了「配方法」，但「求根公式推导」还需要加强。下周建议重点攻克这个薄弱点，加油！"
    },
    "message": ""
}
```

---

### 2.7 AI 答疑

#### POST /api/student/chat

通用答疑对话。学生自由提问，AI 结合学习上下文回答。

**请求体**：
```json
{
    "message": "配方法和公式法有什么区别？",
    "history": [
        {"role": "user", "content": "我最近在学一元二次方程"},
        {"role": "assistant", "content": "好的，一元二次方程是初中数学的重要内容"}
    ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| message | string | 是 | 当前提问内容 |
| history | array | 否 | 最近对话历史，每条含 role(user/assistant) 和 content，最多保留 10 轮 |

**响应**：
```json
{
    "code": 0,
    "data": {
        "reply": "配方法是通过配方把 ax²+bx+c=0 变成 (x+p)²=q 的形式求解，公式法直接代入 x=(-b±√(b²-4ac))/2a。两者的本质是一样的——公式法其实就是对一般形式用配方法推导出来的。建议你先熟练掌握配方法，这样公式法更容易理解。",
        "related_knowledge_points": [
            {"id": "kp_002", "name": "配方法解一元二次方程"},
            {"id": "kp_003", "name": "求根公式推导"}
        ]
    },
    "message": ""
}
```

**实现要点**：
- 系统 Prompt 注入学生当前学习概况（薄弱知识点、已掌握知识点）
- 关联知识点从 Neo4j 关键词匹配或 LLM 输出中提取
- 超时 30s，失败返回友好降级提示
- 对话记录不在服务端持久化，前端自行管理 history

#### POST /api/student/chat/knowledge-point

绑定知识点的上下文答疑。学生在知识点详情页点击「问 AI」时调用。

**请求体**：
```json
{
    "message": "配方法的第一步为什么要把常数项移到右边？",
    "knowledge_point_id": "kp_002",
    "history": []
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| message | string | 是 | 当前提问 |
| knowledge_point_id | string | 是 | 当前知识点 ID |
| history | array | 否 | 对话历史 |

**响应**：
```json
{
    "code": 0,
    "data": {
        "reply": "配方法的核心思想是把方程变成完全平方形式。第一步把常数项移到右边，是为了让左边只剩下含 x 的项，这样我们才能对 x²+bx 这部分进行配方。比如 x²+6x=0，把 0 移过去还是 0，但如果右边有常数比如 x²+6x+5=0，就需要先把 5 移到右边变成 x²+6x=-5。",
        "knowledge_point_name": "配方法解一元二次方程"
    },
    "message": ""
}
```

**实现要点**：
- 系统 Prompt 注入该知识点的名称、描述、前置知识点信息
- 回答范围限定在该知识点及前置知识范围内，避免跑题
- 同上，对话记录前端管理

---

## 三、通用 API

### 3.1 认证（/auth，无 /api 前缀）

> 2026-08-16 补记：本组接口此前未收录进契约文档，现按实际实现定稿（实现详见 `docs/Delivery/2026-07-17-用户认证模块.md`）。

#### POST /auth/register

注册新用户（仅允许注册 student 账号；管理员账号由后台创建）。

**请求体**：
```json
{
    "username": "zhangsan",
    "password": "123456",
    "name": "张三",
    "role": "student"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| username | string | 是 | 登录账号，3-50 字符 |
| password | string | 是 | 密码，最少 6 字符 |
| name | string | 是 | 显示名称，1-50 字符 |
| role | string | 否 | 仅允许 `student`（默认）；传 `admin` 返回 HTTP 403（业务码 40101） |

**响应**：
```json
{
    "code": 0,
    "data": {
        "user_id": "stu_a1b2c3d4",
        "username": "zhangsan",
        "name": "张三",
        "role": "student",
        "avatar": null,
        "created_at": "2026-07-17T10:00:00"
    },
    "message": "注册成功"
}
```

- 用户名已存在 → 业务码 `40900`；请求过于频繁 → HTTP 429 + `40901`。

#### POST /auth/login

登录并获取 JWT Token。

**请求体**：
```json
{
    "username": "zhangsan",
    "password": "123456"
}
```

**响应**：
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

- 用户名或密码错误 / 账号被禁用 → HTTP 401（业务码 `40100`，message 区分）；
- 请求过于频繁 → HTTP 429 + `40901`。

#### GET /auth/me

获取当前登录用户信息（需 `Authorization: Bearer <token>`）。

**响应**：
```json
{
    "code": 0,
    "data": {
        "user_id": "stu_a1b2c3d4",
        "username": "zhangsan",
        "name": "张三",
        "role": "student",
        "avatar": null,
        "created_at": "2026-07-17T10:00:00",
        "last_login_at": "2026-07-17T10:05:00"
    },
    "message": "获取成功"
}
```

### 3.2 健康检查

#### GET /health

健康检查。

```json
{"code": 0, "data": {"status": "ok", "neo4j": true, "sqlserver": true}, "message": ""}
```

---

## 四、接口优先级

| 优先级 | 接口 | 说明 |
|--------|------|------|
| P0 | 知识点 CRUD、题目 CRUD | 最基础，没数据后面都跑不了 |
| P0 | 提交答案 | 答题是核心闭环 |
| P1 | DINA 诊断 | 系统核心算法 |
| P1 | 学习路径 | 系统核心功能 |
| P2 | 诊断解读、路径解释、AI 答疑 | AI 增强体验 |
| P2 | 学生数据看板 | 管理端核心 |
| P3 | 周报 | 锦上添花 |
| P3 | 社交（排行榜/打卡/成就） | 锦上添花 |

---

## 五、接口实现状态（2026-08-16 盘点）

> 前后端并行开发时以此表为准；新接口交付后必须同步更新本表与「六、变更记录」。

| 接口 | 状态 |
|------|:----:|
| GET/POST /api/admin/knowledge-points、GET/PUT/DELETE /api/admin/knowledge-points/{id}、POST /api/admin/knowledge-points/{id}/prerequisites | ✅ |
| GET/POST /api/admin/questions、GET/PUT/DELETE /api/admin/questions/{id}、POST /api/admin/questions/batch-import | ✅ |
| GET /api/admin/students、GET /api/admin/students/{student_id} | 🔲 |
| GET/POST /api/admin/social/achievements、GET /api/admin/social/check-ins | 🔲 |
| GET /api/admin/ai-reports/weekly | 🔲 |
| GET/PUT /api/admin/config | 🔲 |
| GET /api/student/knowledge-points、GET /api/student/knowledge-points/{id} | ✅ |
| POST /api/student/submit-answer、POST /api/student/submit-batch | ✅ |
| POST /api/student/diagnosis | ✅ |
| POST /api/student/diagnosis/explain | 🔲 |
| GET /api/student/path、GET /api/student/path/explain | ✅ |
| GET /api/student/social/leaderboard、POST /api/student/social/check-in、GET /api/student/social/achievements | 🔲 |
| GET /api/student/weekly-report | 🔲 |
| POST /api/student/chat、POST /api/student/chat/knowledge-point | 🔲 |
| POST /auth/register、POST /auth/login、GET /auth/me | ✅ |
| GET /health | ✅ |

---

## 六、变更记录

> 接口有变更必须先改本节，再改代码。

| 日期 | 接口/章节 | 变更内容 | 关联交付 |
|------|-----------|----------|----------|
| （初版） | 全文 | 契约文档初版 | — |
| 2026-08-15 | 1.2 GET /questions | 难度筛选由单值 `difficulty` 修订为 `difficulty_min` / `difficulty_max` 闭区间（可单边使用，下限>上限报参数错误） | `docs/Delivery/2026-08-15-题库管理接口.md` |
| 2026-08-16 | 2.2 submit-batch | 补充响应结构定稿（`results` + `summary`） | `docs/Delivery/2026-08-16-学员端答题接口.md` |
| 2026-08-16 | 通用规范、2.1 | 认证现状定稿（admin 需管理员 Token / 学员写接口需学生 Token / 学员读接口可选）；`mastery_probability` 无数据为 null；认证接口限速 429/40901 | `docs/Delivery/2026-08-16-后端审查问题修复.md` |
| 2026-08-16 | 三、五、六 | 补录 `/auth/*` 三个接口定义；新增业务码对照表、接口实现状态表、变更记录；新增示例数据口径说明 | `docs/Delivery/2026-08-16-文档体系整理.md` |
