# 自适应学习路径（Adaptive_Learning_Path
）系统

基于知识图谱、DINA 认知诊断和个性化路径规划的学习系统。后端使用 FastAPI，SQL Server 保存用户、题目、答题和诊断数据，Neo4j 保存章节、知识点及前置关系；管理端是 Vue 3 + Vite，学生端是 UniApp（H5 + 微信小程序）。

## 目录与架构

```text
server/     FastAPI 后端、测试、SQL 初始化与迁移
admin/      Vue 3 管理端
frontend/   UniApp 学生端（H5 / 微信小程序）
kg-data/    Neo4j CSV 数据、导入和跨库一致性检查
docs/       API 契约、数据库设计、任务卡和交付记录
```

数据职责固定为：Neo4j 保存图谱拓扑；SQL Server 保存用户、题目、Q 矩阵、答题记录、DINA 结果和社交结构化数据。跨库知识点 ID 不建立物理外键，由 `kg-data/scripts/verify_cross_store_ids.py` 只读校验。

## 依赖和环境变量

需要 Python 3.11+、Node.js 20+、npm、SQL Server、Neo4j 5.x，以及本机可用的 SQL Server ODBC Driver 17 或更高版本。后端环境模板位于 [server/.env.example](server/.env.example)，复制为 `server/.env` 后填写本机配置；真实 `.env`、证书和备份不得提交。

生产环境必须设置：

- `ENVIRONMENT=production` 或 `DEBUG=false`；
- `SECRET_KEY` 为至少 32 个字符的随机值，不能使用模板占位符；
- `SQLSERVER_ENCRYPT=yes`，并按证书情况设置 `SQLSERVER_TRUST_SERVER_CERTIFICATE`；
- `CORS_ALLOW_ORIGINS` 为明确的前端来源，不要在生产使用 `*`。

LLM 未配置时核心流程仍可运行，并由业务层返回规则降级内容；不要把 API Key 写进代码、日志或前端。

## 启动顺序

1. 启动 SQL Server 和 Neo4j，创建空数据库 `adaptive_learning`。
2. 仅首次空库执行 `server/sql/init.sql`。脚本会检测已有业务表并终止，避免误删数据。
3. 对已有数据库或初始化后的数据库执行版本化迁移：

   ```powershell
   python server/sql/migrate.py --dry-run
   python server/sql/migrate.py
   ```

   迁移版本记录在 `dbo.schema_migrations`；执行器不会运行 `DROP DATABASE/TABLE/SCHEMA/INDEX`。

4. 导入 Neo4j 演示图谱（增量模式不会清空已有图）：

   ```powershell
   python kg-data/scripts/import_knowledge_graph.py
   python kg-data/scripts/verify_import.py
   python kg-data/scripts/verify_cross_store_ids.py
   ```

   若 Neo4j 凭证曾暴露，在受控本地实例执行交互式轮换；旧密码隐藏输入，新随机密码写入被 Git 忽略的 `server/.env`：

   ```powershell
   python kg-data/scripts/rotate_neo4j_password.py --write-env --confirm
   ```

5. 启动后端：

   ```powershell
   cd server
   python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

6. 另开终端启动管理端或学生端：

   ```powershell
   cd admin
   npm ci
   npm run dev

   cd frontend
   npm ci
   npm run dev:h5
   ```

## 测试和构建

根目录 CI 门禁位于 `.github/workflows/ci.yml`，不使用缓存掩盖依赖缺失，并在任一命令失败时失败。手工执行基线：

```powershell
python server/scripts/check_secrets.py

cd server
python -m pytest tests -q -p no:cacheprovider

cd ../admin
npm ci
npm run build
npm run verify:routes

cd ../frontend
npm ci
npm run verify:auth
npm run verify:session-init
npm run verify:app-startup
npm run verify:diagnosis-entry
npm run verify:learning-entry
npm run verify:home-entry
npm run verify:ai-history
npm run build:h5
npm run build:mp-weixin
```

当前管理端构建会报告约 772 KB 的主 chunk；UniApp/uni-ui 仍会报告 Sass `@import`、legacy JS API 等上游废弃警告。它们会被记录为技术债，不得通过关闭构建失败来掩盖真正错误。

## API 和演示数据

现行接口契约是 [docs/改进计划与任务卡/API契约文档-v2.md](docs/改进计划与任务卡/API契约文档-v2.md)，响应统一为 `{code, data, message}`。Swagger 地址为 `http://localhost:8000/docs`。

演示账号不在仓库中提交真实密码。开发环境可通过 `/auth/register` 创建学生账号；管理员账号应由受控的开发数据库准备流程创建。题目答案只保存在后端，学生取题接口不下发答案和解析。

在已配置且可丢弃的演示数据库中，可交互式准备管理员账号；密码只在终端隐藏输入，不写入仓库、日志或命令历史：

```powershell
cd server
python scripts/prepare_demo_admin.py --username admin_demo --name "演示管理员" --confirm
```

该脚本固定写入 `admin` 角色，发现同名账号或未明确提供 `--confirm` 时拒绝写入。

## 常见问题

- **启动时报默认 Secret 错误**：生产配置仍是模板值或长度不足，生成随机 `SECRET_KEY` 后重启。
- **迁移提示缺少业务表**：先在空数据库执行一次 `server/sql/init.sql`，再运行迁移；不要在非空库重跑初始化脚本。
- **跨库校验失败**：检查 SQL Server 的 `q_matrix` / `user_kp_mastery` 中的知识点 ID 是否存在于 Neo4j `KnowledgePoint.id`。
- **构建有警告但命令成功**：先区分已记录的大包/Sass 上游警告和真正的非零退出；CI 只把命令失败作为门禁失败。

## 当前收口边界

M1～M9已正式通过。M10本地工程和M0本地全链路已独立通过，M0-R1～R5客户端/页面返修全部关闭，依据见 [最终本地复验](docs/改进计划与任务卡/验收记录/2026-10-08-M02-M0-R5复验与本地收口.md)。

当前唯一待闭环项是 [远端CI与合并阻断证据](docs/改进计划与任务卡/tasks/M10-远端CI与合并阻断补证卡.md)。仓库无remote，M10和项目整体尚未最终通过。
