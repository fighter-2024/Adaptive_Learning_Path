# M9 · AI 解读、答疑与周报闭环

## 可直接下发指令

```text
执行 docs/改进计划与任务卡/tasks/M9-AI解读答疑与周报闭环.md。
先阅读 docs/AI开发总则.md 中的 LLM 规范、docs/改进计划与任务卡/API契约文档-v2.md 和综合改进要求。
所有模型调用必须走统一 service，并有规则降级；完成后申请 M0 验收 M9。
```

## 目标

完成 AI 诊断解读、知识点/通用答疑和学习周报，使 AI 成为核心算法结果的解释层，而不是核心流程的单点故障。

## 优先级与依赖

- 优先级：P1/P2
- 前置依赖：M7、M8
- 下游：最终联调

## 必做范围

1. 统一 LLM service：provider、model、timeout、重试、输出校验、日志和降级。
2. Prompt 集中存放，不散落在 router 和页面。
3. 实现或完善：
   - `POST /api/student/diagnosis/explain`；
   - `GET /api/student/path/explain`；
   - `POST /api/student/chat`；
   - `POST /api/student/chat/knowledge-point`；
   - `GET /api/student/weekly-report`。
4. AI 诊断解读包含 strengths、weaknesses、suggestion 和 explanation。
5. 答疑返回关联知识点，前端可跳转；对话历史在前端按契约管理。
6. 周报统计由服务端真实数据计算，LLM 只生成总结；同一周支持缓存和明确失效策略。
7. 完成学生端 AI 解读、聊天、周报页面和管理端 AI 报告查看。
8. 未配置 LLM、超时、返回空内容和格式错误时必须返回规则降级内容。

## 不在范围

- 不让 LLM 直接修改 mastery、题目答案或路径拓扑。
- 不上传密码、Token、API Key 或不必要个人信息。
- 不实现向量数据库或 RAG 平台，除非另立任务并由 M0 批准。

## 验收标准

- [ ] 所有模型调用走同一 service。
- [ ] LLM 不可用时诊断、路径和周报仍有可用内容。
- [ ] 周报统计与数据库一致，AI 只负责总结文本。
- [ ] 知识点答疑上下文只包含必要知识信息。
- [ ] 前端关联知识点卡片可以跳转。
- [ ] 日志中没有 API Key、完整 Token 或敏感输入。
- [ ] 后端测试、管理端、H5 和小程序构建通过。

## 必须提交的证据

- 正常模型调用和强制超时降级各一例。
- 同一周周报缓存命中证据。
- AI 页面截图和关联知识点跳转录屏。
- 敏感信息日志检查结果。
