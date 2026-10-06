"""
SQL Server 关系数据库连接模块

封装 pyodbc，提供连接获取和健康检查。
连接参数从 app.config.settings 读取。
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

import pyodbc

from app.config import settings

logger = logging.getLogger(__name__)


def _build_connection_string() -> str:
    """根据配置拼装 SQL Server 连接字符串

    Returns:
        pyodbc 格式的连接字符串
    """
    params = {
        "DRIVER": f"{{{settings.SQLSERVER_DRIVER}}}",
        "SERVER": f"{settings.SQLSERVER_HOST},{settings.SQLSERVER_PORT}",
        "DATABASE": settings.SQLSERVER_DATABASE,
        "Encrypt": settings.SQLSERVER_ENCRYPT,
        "TrustServerCertificate": settings.SQLSERVER_TRUST_SERVER_CERTIFICATE,
    }

    # Windows 集成认证 vs 用户名密码认证
    if settings.SQLSERVER_TRUSTED_CONNECTION.lower() == "yes":
        params["Trusted_Connection"] = "yes"
    else:
        params["UID"] = settings.SQLSERVER_USER
        params["PWD"] = settings.SQLSERVER_PASSWORD

    return ";".join(f"{k}={v}" for k, v in params.items())


def get_connection() -> pyodbc.Connection:
    """获取一个新的 SQL Server 数据库连接

    每次调用返回新连接，调用方负责在使用后关闭连接。
    推荐通过 context manager 使用：

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(...)

    Returns:
        pyodbc.Connection 实例

    Raises:
        pyodbc.Error: 如果连接失败
    """
    conn_str = _build_connection_string()
    logger.debug("正在连接 SQL Server: %s:%d/%s", settings.SQLSERVER_HOST, settings.SQLSERVER_PORT, settings.SQLSERVER_DATABASE)

    conn = pyodbc.connect(conn_str, timeout=10)
    conn.autocommit = False  # 默认手动事务，显式 commit
    return conn


def get_local_now() -> datetime:
    """获取当前服务器本地时间（业务时间戳统一口径）

    约定（与 JWT 的 UTC 口径区分）：
    - 业务时间戳（created_at / diagnosed_at / last_login_at 等）统一用
      服务器本地时间，与 SQL Server GETDATE() 返回的服务器本地时间一致，
      便于直接比对、按日期分组统计（周报等场景）；
    - 仅 JWT 的 iat/exp 使用 UTC（令牌需要跨时区绝对时间，见 auth_service）。

    Returns:
        当前服务器本地时间（naive datetime）
    """
    return datetime.now()


async def check_sqlserver_health() -> bool:
    """检查 SQL Server 连接是否正常

    执行 SELECT 1 验证连通性。同步的 pyodbc 调用放入线程池执行，
    避免连接超时（最长 10 秒）阻塞事件循环。
    不会抛出异常，失败时记录日志并返回 False。

    Returns:
        True 表示 SQL Server 连接正常
    """

    def _check() -> bool:
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 AS test")
                row = cursor.fetchone()
                return row is not None and row[0] == 1
        except pyodbc.Error as e:
            logger.error(
                "SQL Server 健康检查失败: %s；实际生效配置: %s",
                e,
                settings.describe_sqlserver(),
            )
            return False
        except Exception as e:
            logger.error("SQL Server 健康检查异常: %s", e)
            return False

    return await asyncio.to_thread(_check)
