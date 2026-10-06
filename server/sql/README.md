# SQL Server 初始化与迁移

数据库脚本分成两类：

- `init.sql`：只用于空数据库首次初始化。脚本会在发现任一业务表已存在时立即终止，不会把已有数据库当成空库处理。
- `migrations/NNNN_description.sql`：只包含可审计的增量变更，由 `migrate.py` 按文件名顺序执行，并写入 `dbo.schema_migrations`。迁移执行器会拒绝包含 `DROP DATABASE/TABLE/SCHEMA/INDEX` 的文件。

## 空库初始化

先创建目标数据库，再连接目标数据库执行 `init.sql`。SQL Server Management Studio、`sqlcmd` 或其他受控 SQL 客户端均可执行；不要在生产库重复执行它。

## 非空库增量升级

在项目根目录执行：

```powershell
python server/sql/migrate.py --dry-run
python server/sql/migrate.py
```

执行器从 `server/.env` 或进程环境读取 `SQLSERVER_*` 配置。每个迁移在独立事务中运行：

1. 迁移成功后写入版本记录并提交；
2. 任一批次失败则回滚当前迁移，不标记为已执行；
3. 修复数据或脚本后重新执行同一版本；
4. 不使用 `DROP` 验证升级结果。

## 验证与恢复

迁移后使用 SQL Server 的约束/索引元数据查询确认版本和约束，再运行：

```sql
-- 在目标数据库中执行，只读输出表、行数、约束和迁移版本
server/sql/verify_migration.sql
```

```powershell
python kg-data/scripts/verify_cross_store_ids.py
```

恢复优先使用数据库平台的备份/时间点恢复能力；在执行迁移前保存数据库备份或快照，记录迁移版本和执行时间。迁移脚本不自动回滚历史版本，也不自动删除数据。
