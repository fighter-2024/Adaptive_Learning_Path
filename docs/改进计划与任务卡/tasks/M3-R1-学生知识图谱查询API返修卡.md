# M3-R1 · 学生知识图谱查询 API 返修卡

## 可直接下发指令

```text
执行 docs/改进计划与任务卡/tasks/M3-R1-学生知识图谱查询API返修卡.md。
先阅读 M3 原任务卡、API契约文档-v2 和 M0 验收手册。重点修复 focus 截断、完整前置语义和查询范围。
不得只修改测试适配现状。完成真实 Neo4j/SQL Server 联调后申请 M0 复验：M3-R1。
```

## 退回原因

1. **P0：focus 节点可能被截断。**候选 ID 按 ID 排序后直接 `eligible_ids[:max_nodes]`，当 focus 排在截断范围外时，`meta.focus_id` 有值但 `nodes` 中不存在该节点。
2. **P0：截断子图可能产生错误的 locked 和推荐结果。**当前只加载返回节点之间的 `PREREQUISITE`；返回节点如果存在图外未掌握前置，会被错误标记为未锁定，个性化推荐也可能忽略真实拓扑约束。
3. **P1：默认请求先读取全部候选 ID 和全部掌握度，再由 Python 裁剪。**这不满足原任务卡的数据库侧范围限制要求，并可能触发 SQL Server 参数数量和大图性能问题。
4. **证据缺失。**仅有模拟测试与静态响应示例，未提交真实 Neo4j、SQL Server 三种 view 响应和查询次数证据。

## 必须修复的语义

### 1. focus 保证

- `focus_id` 存在时，返回 `nodes` 必须包含该知识点。
- `max_nodes` 仍约束整个 `nodes` 数组，包括 course/chapter 结构节点。
- 当容量不足时优先保留 focus，再按距离和稳定规则选择邻居；不得仅按 ID 前缀截断。
- `meta.returned_nodes == len(nodes)`，`truncated` 和 `total_nodes` 保持准确。

### 2. 锁定与推荐正确性

- 返回知识点的 `locked` 必须基于它在完整查询范围内的直接前置关系和当前学生掌握度计算，不能只看已经渲染的边。
- personalized 视图必须复用或对齐正式学习路径算法；图外前置节点不能导致违规推荐。
- 环路继续返回明确图数据库错误，不得返回部分成功推荐。

### 3. 查询范围与批量读取

- 默认查询应在 Neo4j 侧完成计数、排序和有界节点选择，不先把完整图谱节点属性加载到 Python。
- 掌握度必须保持批量查询，禁止 N+1。
- `include_mastered=false` 时仍需准确计算 eligible 节点和 meta；可采用“先批量取当前用户已掌握 ID，再传入 Neo4j 做排除、计数和有界选择”等等价设计。
- 设计需能处理超过 SQL Server 单次参数上限的数据规模；必要时使用临时表、分批查询或其他有界方案。

## 必须新增的自动化测试

- focus 的 ID 排在所有候选最后，`max_nodes=1/2/3` 时仍被返回。
- focus 邻居数超过上限时，按距离优先且结果稳定。
- 返回节点存在未渲染的外部前置节点时，`locked=true`。
- 个性化推荐不越过未掌握前置约束。
- 500 个和更大模拟图的 `max_nodes`、meta 与查询调用规模测试。
- `include_mastered=false` 的全掌握、部分掌握、无掌握记录场景。
- 学生 A、学生 B 使用同一图谱时，掌握状态互不泄露。
- Neo4j、SQL Server 异常继续分别返回 `50002`、`50001`。

## 验收命令

```powershell
cd server
python -m pytest tests/test_graph.py tests/test_admin_graph.py -q -p no:cacheprovider
python -m pytest tests -q -p no:cacheprovider
```

## 必须提交的真实证据

- 使用真实 student Token 的 tree、network、personalized 三种响应，敏感 Token 必须脱敏。
- focus + 小 `max_nodes` 的真实响应，证明 focus 位于 nodes 中。
- `include_mastered=false` 的真实响应。
- 查询日志或计数，分别说明 Neo4j 查询次数和 SQL Server 批量查询次数，无逐节点 SQL。
- 两个学生不同 mastery 的隔离证据。
- 数据库不可用时非 `code=0` 空图的响应。

## 契约限制

- 优先保持现有 URL 和 GraphData 字段兼容。
- 如确需改变截断语义或增加 meta 字段，必须先更新 `API契约文档-v2.md`，写明对 M4、M5 的影响后再编码。

