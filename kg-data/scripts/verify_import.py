"""
验证 Neo4j 知识图谱导入结果

用法:
    cd kg-data
    python scripts/verify_import.py --password <your-password>
    python scripts/verify_import.py                 # 从 .env 读取连接信息

连接参数优先级：CLI 参数 > .env 文件 > 内置默认值
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict

from neo4j import GraphDatabase, Driver
from neo4j.exceptions import Neo4jError, ServiceUnavailable

# ==================== 日志配置 ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DOTENV_PATH = PROJECT_ROOT / "server" / ".env"


def load_dotenv(dotenv_path: Path) -> Dict[str, str]:
    """从 .env 文件读取键值对（简易解析）

    Args:
        dotenv_path: .env 文件路径

    Returns:
        键值对字典
    """
    env_vars: Dict[str, str] = {}
    if not dotenv_path.exists():
        return env_vars
    with open(dotenv_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value:
                env_vars[key] = value
    return env_vars


def verify(driver: Driver) -> bool:
    """运行验证查询，检查图谱数据完整性

    Args:
        driver: Neo4j 驱动

    Returns:
        True 表示验证通过
    """
    all_ok = True

    with driver.session() as session:
        # 1. 节点统计
        result = session.run("MATCH (n) RETURN labels(n) AS labels, count(n) AS cnt")
        logger.info("=== 节点统计 ===")
        kp_count = 0
        ch_count = 0
        for row in result:
            labels = row["labels"]
            cnt = row["cnt"]
            logger.info("  %s: %d", labels, cnt)
            if "KnowledgePoint" in labels:
                kp_count = cnt
            elif "Chapter" in labels:
                ch_count = cnt

        # 2. 关系统计
        result = session.run(
            "MATCH ()-[r]->() RETURN type(r) AS rel_type, count(r) AS cnt"
        )
        logger.info("=== 关系统计 ===")
        belongs_to = prereq = 0
        for row in result:
            rel_type = row["rel_type"]
            cnt = row["cnt"]
            logger.info("  %s: %d", rel_type, cnt)
            if rel_type == "BELONGS_TO":
                belongs_to = cnt
            elif rel_type == "PREREQUISITE":
                prereq = cnt

        # 3. 抽查：配方法的前置知识点
        result = session.run("""
            MATCH (kp:KnowledgePoint {id: 'kp_013'})<-[:PREREQUISITE]-(pre:KnowledgePoint)
            RETURN kp.name AS target, collect(pre.name) AS prerequisites
        """)
        logger.info("=== 抽查：配方法(kp_013)的前置知识点 ===")
        for row in result:
            logger.info("  %s ← %s", row["target"], row["prerequisites"])
            expected = {"直接开平方法", "一元二次方程的定义"}
            actual = set(row["prerequisites"])
            if actual != expected:
                logger.error("  前置不匹配！期望 %s，实际 %s", expected, actual)
                all_ok = False

        # 4. 抽查：ch_03 章节的知识点数量
        result = session.run("""
            MATCH (kp:KnowledgePoint)-[:BELONGS_TO]->(c:Chapter {id: 'ch_03'})
            RETURN c.name AS chapter, count(kp) AS cnt
        """)
        logger.info("=== 抽查：一元二次方程(ch_03)的知识点数 ===")
        for row in result:
            logger.info("  %s: %d 个知识点", row["chapter"], row["cnt"])
            if row["cnt"] != 7:
                logger.error("  数量不匹配！期望 7，实际 %d", row["cnt"])
                all_ok = False

        # 5. 环检测：确保无环
        logger.info("=== 环检测 ===")
        # Neo4j 不直接支持环检测，用路径查询验证：不存在长度 > 1 的闭环
        result = session.run("""
            MATCH path = (a:KnowledgePoint)-[:PREREQUISITE*2..20]->(a)
            RETURN count(path) AS cycle_count
        """)
        cycle_count = result.single()["cycle_count"]
        if cycle_count > 0:
            logger.error("  检测到 %d 个环！", cycle_count)
            all_ok = False
        else:
            logger.info("  无环 ✓")

        # 汇总
        logger.info("=== 汇总 ===")
        logger.info(
            "节点: Chapter(%d) + KnowledgePoint(%d) = %d",
            ch_count, kp_count, ch_count + kp_count,
        )
        logger.info("关系: BELONGS_TO(%d) + PREREQUISITE(%d) = %d",
                     belongs_to, prereq, belongs_to + prereq)

    return all_ok


def main() -> None:
    """验证脚本主入口"""
    parser = argparse.ArgumentParser(description="验证 Neo4j 知识图谱导入结果")
    parser.add_argument("--uri", default=None, help="Neo4j bolt URI")
    parser.add_argument("--user", default=None, help="Neo4j 用户名")
    parser.add_argument("--password", default=None, help="Neo4j 密码")
    args = parser.parse_args()

    env_vars = load_dotenv(DOTENV_PATH)

    uri = args.uri or env_vars.get("NEO4J_URI", "bolt://localhost:7687")
    user = args.user or env_vars.get("NEO4J_USER", "neo4j")
    password = args.password or env_vars.get("NEO4J_PASSWORD", "")

    logger.info("连接 Neo4j: %s (用户: %s)", uri, user)

    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            session.run("RETURN 1 AS test").single()
    except (ServiceUnavailable, Neo4jError) as e:
        logger.error("无法连接 Neo4j: %s", e)
        sys.exit(1)

    try:
        ok = verify(driver)
        if ok:
            logger.info("验证通过 ✓")
        else:
            logger.error("验证发现问题 ✗")
            sys.exit(1)
    finally:
        driver.close()

    logger.info("验证完成！")


if __name__ == "__main__":
    main()
