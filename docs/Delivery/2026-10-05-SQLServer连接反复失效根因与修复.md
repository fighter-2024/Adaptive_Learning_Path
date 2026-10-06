# 交付记录：SQL Server 连接反复失效的根因与修复

> 执行日期：2026-10-05（Asia/Shanghai）
> 关联：M1/M3/M5/M10-R2 验收环境、[R2 验收环境阻塞记录](../改进计划与任务卡/阻塞记录/2026-10-04-R2验收环境阻塞.md)

## 1. 现象

交付过程中反复出现「应用连不上 SQL Server」：`GET /health` 返回
`sqlserver: false`。此前每次都是重启 8000 端口的 FastAPI 后恢复，但过一段时间
又会复现，且曾被归因为「SQL Server 实例的加密/证书配置需要修复」。

## 2. 根因（已可复现）

**不是实例配置问题**。实测确认实例从未强制加密：

| 检查项 | 实测值 |
| --- | --- |
| `SuperSocketNetLib\ForceEncryption` | `0` |
| `SuperSocketNetLib\Certificate` | 空（未指定用户证书） |
| ERRORLOG 启动行 | `A self-generated certificate was successfully loaded for encryption.` |
| `sqlcmd -S localhost -E`（不请求加密） | 成功 |

真正的根因是 **配置来源优先级**：`pydantic-settings` 默认让**进程环境变量覆盖
`.env` 文件**。因此任何会话中残留的 `SQLSERVER_ENCRYPT=yes` /
`SQLSERVER_TRUST_SERVER_CERTIFICATE=no` 都会静默生效，而实例使用的是启动时
自生成的证书、客户端并未信任它，于是 TLS 握手在登录之前就终止：

```
SQLSTATE = 08001
[08001] SSL 提供程序: 证书链是由不受信任的颁发机构颁发的。 (-2146893019)
[08001] 客户端无法建立连接 (-2146893019)
```

`08001` 是 ODBC 的连接异常类状态码，不含原因；`-2146893019` 即
`0x80090325` = `SEC_E_UNTRUSTED_ROOT`。此时 SQL Server 错误日志中**没有任何
登录记录**——连接根本没到达实例，这一点正是区分「服务端强制加密」与
「客户端要求加密」的关键证据。

### 复现命令

```powershell
# 旧代码下：/health 返回 sqlserver=false，日志即上述 08001
$env:SQLSERVER_ENCRYPT='yes'; $env:SQLSERVER_TRUST_SERVER_CERTIFICATE='no'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8099
```

## 3. 修改内容

| 文件 | 改动 |
| --- | --- |
| `server/app/config/settings.py` | 新增 `settings_customise_sources`，把 **dotenv 提到 env 之前**：`server/.env` 成为权威配置来源，环境变量不再静默覆盖它；`.env` 未定义的键仍可由环境变量提供，显式初始化参数（含测试）仍为最高优先级 |
| `server/app/config/settings.py` | 新增 `Settings.describe_sqlserver()`，返回**不含密码**的有效连接参数摘要 |
| `server/app/main.py` | 启动时打印 SQL Server 与 Neo4j 的有效配置，故障可直接对照 |
| `server/app/db/sqlserver.py` | 健康检查失败时，日志同时输出原始异常与有效配置 |
| `server/scripts/setup_sqlserver_tls_cert.ps1` | 新增（需管理员）：为实例配置客户端信任的 TLS 证书，支持 `-Rollback` |

设计取舍：本项目以 `server/.env` 为唯一权威配置来源（README 亦如此约定），
且当前无使用环境变量注入的部署或 CI 入口，故反转来源优先级是安全的；作为
交换，部署若需按环境覆盖，应改 `.env` 而不是依赖进程环境变量。

## 4. 验证证据

| 检查项 | 命令 | 结果 |
| --- | --- | --- |
| 优先级生效 | 置 `SQLSERVER_ENCRYPT=yes`/`TRUST_SERVER_CERTIFICATE=no`/`SQLSERVER_HOST=10.0.0.99` 后读 settings | 实际生效仍为 `no` / `yes` / `localhost` |
| 故障复现实验（修复后） | 同敌意环境变量启动 8099 实例并请求 `/health` | `{"status":"ok","neo4j":true,"sqlserver":true}` |
| 后端测试基线 | `cd server; python -m pytest tests -q` | **330 passed** |
| 生产端口回归 | 重启 8000 端口后 `GET /health` | `{"status":"ok","neo4j":true,"sqlserver":true}` |
| 启动日志 | 8000 端口启动输出 | 打印 `SQL Server 有效配置: driver=...; Encrypt=no; TrustServerCertificate=yes; Trusted_Connection=yes` |

## 5. 服务器证书加固（2026-10-05 21:10 已执行完成）

此前 `Encrypt=yes` + `TrustServerCertificate=no` 会失败，因为实例使用的是启动时
自生成的证书。已由环境负责人以管理员身份执行：

```powershell
powershell -ExecutionPolicy Bypass -File server\scripts\setup_sqlserver_tls_cert.ps1
```

脚本创建带 SAN（`localhost`、`WBMSTR`、`127.0.0.1`）的服务器证书、授予
`NT Service\MSSQLSERVER` 私钥读取权限、把公钥导入 `LocalMachine\Root`、
写入实例 `Certificate` 注册表值并重启服务。

执行结果：

| 项 | 值 |
| --- | --- |
| 证书指纹 | `C53014E12F132CB8A9A1471510B848C73BF29478` |
| 主题 / SAN | `CN=WBMSTR` / `localhost`、`WBMSTR`、`127.0.0.1` |
| 有效期至 | 2031-10-05 |
| 落地位置 | `LocalMachine\My`（含私钥） + `LocalMachine\Root`（受信任） |
| 实例启动日志 | `The certificate [Cert Hash(sha1) "C530..."] was successfully loaded for encryption.` |
| `ForceEncryption` | 仍为 `0`（未强制，客户端可自选） |

### 验收结果（ODBC Driver 17，`Trusted_Connection=yes`）

| 组合 | 结果 |
| --- | --- |
| `Encrypt=no` + `TrustServerCertificate=yes` | 通过 |
| `Encrypt=yes` + `TrustServerCertificate=no`（此前失败） | **通过** |
| `Encrypt=yes` + `TrustServerCertificate=yes` | 通过 |
| 同上，服务器名用 `WBMSTR` / `127.0.0.1` | 通过（SAN 匹配正确） |
| `sqlcmd -S localhost -E -N`（要求加密、不加 `-C`） | 通过 |
| `GET /health` | `{"status":"ok","neo4j":true,"sqlserver":true}` |

> 说明：`Encrypt=strict` 是 ODBC Driver 18 / Microsoft.Data.SqlClient 4.0+ 的取值，
> Driver 17 只接受 `yes`/`no`，报 `为连接字符串属性 'Encrypt' 指定的值无效` 属预期。

撤销命令：

```powershell
powershell -ExecutionPolicy Bypass -File server\scripts\setup_sqlserver_tls_cert.ps1 -Rollback
```

脚本运行前会校验管理员权限并给出明确提示；重启服务前记录依赖服务（如
`SQLSERVERAGENT`）并在就绪后拉起；写入注册表后若服务未能就绪，会自动回滚
`Certificate` 值并再次重启。

### 附带说明：SQLSERVERAGENT 当前为 Stopped

与本次改动无关。事件日志记录 `2026-10-05 12:18:57 SQLServerAgent service
successfully stopped`（干净停止，早于证书脚本 9 小时）。其作业均为 MDS 相关
（`MDS_123_*`，目标库 `123` 不可访问，持续失败并周期性写入 18456），与本项目
无关；服务为自动启动，重启机器即恢复。如需立即恢复：
`Start-Service SQLSERVERAGENT`（需管理员）。

> **编码要求**：本脚本含中文注释，必须保存为 **UTF-8 with BOM**。
> Windows PowerShell 5.1 对无 BOM 的 `.ps1` 按 ANSI 代码页读取，中文会被打乱
> 并导致字符串引号失配、报出一连串 `缺少表达式` / `字符串缺少终止符` 语法错误
> （已实际踩到）。后续新增含非 ASCII 内容的 PowerShell 脚本请一并遵守。

**未执行前的实际影响**：`.env` 已固定为 `Encrypt=no` +
`TrustServerCertificate=yes`，且该组合不再可能被环境变量覆盖，因此日常开发
链路已经稳定；只有显式按生产要求改用 `Encrypt=yes` 时才需要上述证书。

## 6. 注意事项

- 若确需用环境变量临时覆盖配置，请改为修改 `server/.env`；本项目的来源优先级已反转。
- `/health` 的响应结构与 `docs/API契约文档.md` 一致，本次未改动，只增加日志。
- 重启后端请使用不含 `SQLSERVER_*` / `NEO4J_*` 的干净 shell；即便残留也已不再影响结果。
