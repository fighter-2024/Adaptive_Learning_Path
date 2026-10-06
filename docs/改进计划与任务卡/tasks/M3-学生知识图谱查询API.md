# M3 · 学生知识图谱查询 API

## 可直接下发指令

```text
执行 docs/改进计划与任务卡/tasks/M3-学生知识图谱查询API.md。
先阅读 docs/AI开发总则.md、docs/改进计划与任务卡/API契约文档-v2.md、00-范围与决策、02-增量接口与数据契约。
先定稿契约，再实现 models/router/service/tests，完成后申请 M0 验收 M3。
```

## 目标

提供可供树图、局部关系网和个性化路径共用的统一图谱读取接口，同时合并 Neo4j 拓扑、SQL Server 掌握度和现有路径推荐结果。

## 优先级与依赖

- 优先级：P0
- 前置依赖：无
- 下游：M4、M5

## 必做范围

1. 将以下接口定稿并写入正式 API 契约：
   - `GET /api/student/graph`
   - `GET /api/student/graph/{id}/neighbors`
   - `GET /api/admin/graph`
2. 新建明确的 Pydantic 图谱响应模型：node、edge、meta。
3. Neo4j 返回 Chapter、KnowledgePoint、BELONGS_TO、PREREQUISITE。
4. 学生接口按当前学生批量合并 mastery/status；个性化视图合并推荐顺序和理由。
5. 实现 `focus_id`、`depth`、`max_nodes`、`include_mastered`。
6. 限制默认节点数并准确返回 `truncated`。
7. 邻居接口支持 incoming/outgoing/both，避免 N+1。
8. 课程根节点由 service 生成即可，不强制修改 Neo4j schema。
9. 增加鉴权、空图、非法 focus、截断、环路和数据库异常测试。

## 不在范围

- 不实现前端图谱。
- 不扩充到 500 个真实知识点。
- 不持久化节点坐标。
- 不新增未经确认的 Neo4j 关系类型。

## 性能要求

- 默认请求只查询所需子图，不先加载全图再在 Python 中裁剪。
- 掌握度使用批量 SQL 查询。
- 测试至少覆盖 500 个模拟节点时的截断和响应结构正确性。

## 验收标准

- [ ] 三个接口与正式契约一致。
- [ ] tree/network/personalized 返回同一标准结构。
- [ ] 学生 A 无法看到学生 B 的 mastery。
- [ ] 缺少有效学生 Token 时，个性化接口返回 401，不冒充匿名个性化。
- [ ] `max_nodes` 生效且 meta 数量准确。
- [ ] Neo4j/SQL Server 异常不会返回 code 0 空图。
- [ ] 后端全量测试通过。

## 必须提交的证据

- 三种 view 的响应示例。
- 聚焦节点和截断场景测试。
- 查询次数或日志证据，说明没有按节点逐条查询 SQL。
