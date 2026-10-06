"""
Neo4j 图数据库连接模块

封装 neo4j-driver，提供驱动单例和健康检查。
连接参数从 app.config.settings 读取。
"""

import asyncio
import logging
from typing import Optional

from neo4j import GraphDatabase, Driver
from neo4j.exceptions import Neo4jError

from app.config import settings

logger = logging.getLogger(__name__)

# 模块级驱动实例（懒加载）
_driver: Optional[Driver] = None


def get_driver() -> Driver:
    """获取 Neo4j 驱动单例

    首次调用时根据配置创建驱动实例，后续调用复用同一实例。

    Returns:
        Neo4j Driver 实例

    Raises:
        ValueError: 如果 NEO4J_PASSWORD 未配置（生产环境必填）
        Neo4jError: 如果连接失败
    """
    global _driver

    if _driver is None:
        # 安全检查：生产环境不允许空密码
        if not settings.NEO4J_PASSWORD:
            logger.warning("NEO4J_PASSWORD 未设置，Neo4j 连接将使用空密码（仅开发环境允许）")

        logger.info(
            "正在连接 Neo4j: %s (用户: %s)",
            settings.NEO4J_URI,
            settings.NEO4J_USER,
        )

        _driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
            max_connection_lifetime=3600,  # 连接最大存活时间（秒）
        )

    return _driver


def close_driver() -> None:
    """关闭 Neo4j 驱动，释放所有连接池资源"""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
        logger.info("Neo4j 驱动已关闭")


async def check_neo4j_health() -> bool:
    """检查 Neo4j 连接是否正常

    发送一条简单的 Cypher 查询验证连通性。同步的驱动调用放入线程池
    执行，避免连接超时阻塞事件循环。
    不会抛出异常，失败时记录日志并返回 False。

    Returns:
        True 表示 Neo4j 连接正常
    """

    def _check() -> bool:
        try:
            driver = get_driver()
            with driver.session() as session:
                result = session.run("RETURN 1 AS test")
                record = result.single()
                return record is not None and record["test"] == 1
        except Neo4jError as e:
            logger.error("Neo4j 健康检查失败: %s", e)
            return False
        except Exception as e:
            logger.error("Neo4j 健康检查异常: %s", e)
            return False

    return await asyncio.to_thread(_check)
