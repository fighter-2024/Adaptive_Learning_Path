"""
知识图谱数据导入 Neo4j 脚本

从 kg-data/data/knowledge_points/ 下的 CSV 文件读取知识点、章节和前置依赖数据，
批量导入 Neo4j 图数据库。

用法:
    cd kg-data
    python scripts/import_knowledge_graph.py --force              # 清空后全量导入
    python scripts/import_knowledge_graph.py                      # 增量导入（不会清空）
    python scripts/import_knowledge_graph.py --help               # 查看帮助

连接参数优先级：CLI 参数 > .env 文件 > 内置默认值
"""

import argparse
import csv
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

from neo4j import GraphDatabase, Driver
from neo4j.exceptions import Neo4jError, ServiceUnavailable

# ==================== 日志配置 ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ==================== 常量 ====================

# 脚本所在目录向上找到项目根
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "kg-data" / "data" / "knowledge_points"
DOTENV_PATH = PROJECT_ROOT / "server" / ".env"


# ==================== 配置读取 ====================

def load_dotenv(dotenv_path: Path) -> Dict[str, str]:
    """从 .env 文件读取键值对（简易解析，不依赖 python-dotenv）

    Args:
        dotenv_path: .env 文件路径

    Returns:
        键值对字典（忽略注释行和空行）
    """
    env_vars: Dict[str, str] = {}
    if not dotenv_path.exists():
        logger.debug(".env 文件不存在: %s", dotenv_path)
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


# ==================== Neo4j 连接 ====================

def connect_neo4j(uri: str, user: str, password: str) -> Driver:
    """连接 Neo4j 并验证连通性

    Args:
        uri: Neo4j bolt URI，如 bolt://localhost:7687
        user: 用户名
        password: 密码

    Returns:
        Neo4j Driver 实例

    Raises:
        ServiceUnavailable: 连接不可达
        Neo4jError: 认证失败或其他 Neo4j 错误
    """
    logger.info("连接 Neo4j: %s (用户: %s)", uri, user)
    driver = GraphDatabase.driver(uri, auth=(user, password))

    try:
        with driver.session() as session:
            result = session.run("RETURN 1 AS test")
            record = result.single()
            if record and record["test"] == 1:
                logger.info("Neo4j 连接成功")
            else:
                raise ServiceUnavailable("Neo4j 连通性验证失败")
    except Exception:
        driver.close()
        raise

    return driver


# ==================== 清空数据 ====================

def clear_graph(driver: Driver) -> int:
    """清空 Neo4j 图中所有节点和关系

    Args:
        driver: Neo4j 驱动

    Returns:
        删除的节点数
    """
    logger.warning("正在清空 Neo4j 中所有节点和关系...")
    with driver.session() as session:
        result = session.run("MATCH (n) DETACH DELETE n RETURN count(n) AS deleted")
        record = result.single()
        deleted = record["deleted"] if record else 0
        logger.info("已删除 %d 个节点", deleted)
        return deleted


# ==================== CSV 读取 ====================

def read_csv(filepath: Path) -> List[Dict[str, str]]:
    """读取 CSV 文件，返回字典列表

    Args:
        filepath: CSV 文件路径

    Returns:
        每行一个字典，列名为键

    Raises:
        FileNotFoundError: 文件不存在
    """
    if not filepath.exists():
        raise FileNotFoundError(f"CSV 文件不存在: {filepath}")

    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = [row for row in reader]

    logger.info("读取 %s: %d 行", filepath.name, len(rows))
    return rows


# ==================== 环检测 ====================

def detect_cycles(prerequisite_pairs: List[Tuple[str, str]]) -> List[List[str]]:
    """使用 DFS 检测前置依赖图中的环

    基于邻接表实现的深度优先搜索，用三色标记法检测后向边。

    Args:
        prerequisite_pairs: (source, target) 元组列表，source 是前置知识点的 ID

    Returns:
        检测到的所有环（每个环是一个节点 ID 列表）；空列表表示无环
    """
    # 构建邻接表
    adjacency: Dict[str, List[str]] = {}
    all_nodes: set = set()
    for src, tgt in prerequisite_pairs:
        adjacency.setdefault(src, []).append(tgt)
        all_nodes.add(src)
        all_nodes.add(tgt)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {node: WHITE for node in all_nodes}
    cycles: List[List[str]] = []

    def dfs(node: str, path: List[str]) -> None:
        color[node] = GRAY
        path.append(node)
        for neighbor in adjacency.get(node, []):
            if color.get(neighbor, WHITE) == GRAY:
                # 找到环：从 path 中提取环的部分
                cycle_start = path.index(neighbor)
                cycles.append(path[cycle_start:] + [neighbor])
            elif color.get(neighbor, WHITE) == WHITE:
                dfs(neighbor, path)
        path.pop()
        color[node] = BLACK

    for node in all_nodes:
        if color[node] == WHITE:
            dfs(node, [])

    return cycles


# ==================== 批量导入 ====================

def import_chapters(driver: Driver, chapters: List[Dict[str, str]]) -> int:
    """批量导入 Chapter 节点

    使用 MERGE 避免重复创建，按 chapter_id 去重。

    Args:
        driver: Neo4j 驱动
        chapters: 章节数据列表

    Returns:
        实际创建的节点数（MERGE 会返回 0 或 1，累加即为新建数）
    """
    created = 0
    with driver.session() as session:
        for ch in chapters:
            result = session.run(
                """
                MERGE (c:Chapter {id: $id})
                ON CREATE SET c.name = $name, c.sort_order = toInteger($sort_order)
                ON MATCH SET c.name = $name, c.sort_order = toInteger($sort_order)
                RETURN c.id AS id, c.name AS name
                """,
                id=ch["id"],
                name=ch["name"],
                sort_order=ch.get("sort_order", "0"),
            )
            record = result.single()
            if record:
                logger.debug("Chapter 节点: %s (%s)", record["id"], record["name"])
                created += 1
    logger.info("Chapter 节点导入完成: 处理 %d 条，%d 个节点", len(chapters), created)
    return created


def import_knowledge_points(
    driver: Driver, kps: List[Dict[str, str]]
) -> int:
    """批量导入 KnowledgePoint 节点

    使用 MERGE 按 id 去重。属性包含 name, description, difficulty,
    estimated_time, chapter_id, sort_order。

    Args:
        driver: Neo4j 驱动
        kps: 知识点数据列表

    Returns:
        实际创建/更新的节点数
    """
    created = 0
    with driver.session() as session:
        for kp in kps:
            result = session.run(
                """
                MERGE (k:KnowledgePoint {id: $id})
                ON CREATE SET
                    k.name = $name,
                    k.description = $description,
                    k.difficulty = toFloat($difficulty),
                    k.estimated_time = toInteger($estimated_time),
                    k.chapter_id = $chapter_id,
                    k.sort_order = toInteger($sort_order)
                ON MATCH SET
                    k.name = $name,
                    k.description = $description,
                    k.difficulty = toFloat($difficulty),
                    k.estimated_time = toInteger($estimated_time),
                    k.chapter_id = $chapter_id,
                    k.sort_order = toInteger($sort_order)
                RETURN k.id AS id, k.name AS name
                """,
                id=kp["id"],
                name=kp["name"],
                description=kp.get("description", ""),
                difficulty=kp.get("difficulty", "0.3"),
                estimated_time=kp.get("estimated_time", "25"),
                chapter_id=kp.get("chapter_id", ""),
                sort_order=kp.get("sort_order", "0"),
            )
            record = result.single()
            if record:
                logger.debug("KnowledgePoint 节点: %s (%s)", record["id"], record["name"])
                created += 1
    logger.info("KnowledgePoint 节点导入完成: 处理 %d 条，%d 个节点", len(kps), created)
    return created


def import_belongs_to(driver: Driver, kps: List[Dict[str, str]]) -> int:
    """批量创建 BELONGS_TO 关系（KnowledgePoint → Chapter）

    为每个知识点创建到所属章节的归属关系。使用 MERGE 避免重复。

    Args:
        driver: Neo4j 驱动
        kps: 知识点数据列表（需含 chapter_id）

    Returns:
        创建的关系数
    """
    created = 0
    with driver.session() as session:
        for kp in kps:
            chapter_id = kp.get("chapter_id", "")
            if not chapter_id:
                logger.warning("知识点 %s 缺少 chapter_id，跳过 BELONGS_TO", kp["id"])
                continue
            result = session.run(
                """
                MATCH (k:KnowledgePoint {id: $kp_id})
                MATCH (c:Chapter {id: $chapter_id})
                MERGE (k)-[r:BELONGS_TO]->(c)
                RETURN type(r) AS rel_type
                """,
                kp_id=kp["id"],
                chapter_id=chapter_id,
            )
            if result.single():
                created += 1
    logger.info("BELONGS_TO 关系导入完成: %d 条", created)
    return created


def import_prerequisites(
    driver: Driver, prereqs: List[Dict[str, str]]
) -> Tuple[int, List[List[str]]]:
    """批量创建 PREREQUISITE 关系（source → target）

    语义：source 是 target 的前置知识点。导入前先检测环。

    Args:
        driver: Neo4j 驱动
        prereqs: 前置关系列表，每行含 source_id 和 target_id

    Returns:
        (创建的关系数, 检测到的环列表)
    """
    pairs = [(r["source_id"], r["target_id"]) for r in prereqs]

    # 环检测
    cycles = detect_cycles(pairs)
    if cycles:
        logger.error("检测到 %d 个环，拒绝创建 PREREQUISITE 关系:", len(cycles))
        for i, cycle in enumerate(cycles, 1):
            logger.error("  环 %d: %s", i, " → ".join(cycle))
        return 0, cycles

    created = 0
    with driver.session() as session:
        for source_id, target_id in pairs:
            result = session.run(
                """
                MATCH (src:KnowledgePoint {id: $source_id})
                MATCH (tgt:KnowledgePoint {id: $target_id})
                MERGE (src)-[r:PREREQUISITE]->(tgt)
                RETURN type(r) AS rel_type
                """,
                source_id=source_id,
                target_id=target_id,
            )
            if result.single():
                created += 1
    logger.info("PREREQUISITE 关系导入完成: %d 条（无环）", created)
    return created, cycles


# ==================== 统计查询 ====================

def query_graph_stats(driver: Driver) -> Dict[str, int]:
    """查询当前图谱的统计信息

    Args:
        driver: Neo4j 驱动

    Returns:
        包含 node_count、kp_count、chapter_count、belongs_to_count、
        prereq_count 的字典
    """
    stats: Dict[str, int] = {}
    with driver.session() as session:
        # 总节点数
        result = session.run("MATCH (n) RETURN count(n) AS cnt")
        stats["node_count"] = result.single()["cnt"]

        # 各类型数量
        result = session.run("MATCH (k:KnowledgePoint) RETURN count(k) AS cnt")
        stats["kp_count"] = result.single()["cnt"]

        result = session.run("MATCH (c:Chapter) RETURN count(c) AS cnt")
        stats["chapter_count"] = result.single()["cnt"]

        result = session.run("MATCH ()-[r:BELONGS_TO]->() RETURN count(r) AS cnt")
        stats["belongs_to_count"] = result.single()["cnt"]

        result = session.run("MATCH ()-[r:PREREQUISITE]->() RETURN count(r) AS cnt")
        stats["prereq_count"] = result.single()["cnt"]

    return stats


# ==================== 主入口 ====================

def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="知识图谱数据导入 Neo4j — 从 CSV 批量导入知识点、章节和前置依赖",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="导入前清空 Neo4j 中所有已有数据（DETACH DELETE 全部节点）",
    )
    parser.add_argument(
        "--uri",
        default=None,
        help="Neo4j bolt URI（默认从 .env 读取 NEO4J_URI，fallback: bolt://localhost:7687）",
    )
    parser.add_argument(
        "--user",
        default=None,
        help="Neo4j 用户名（默认从 .env 读取 NEO4J_USER，fallback: neo4j）",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Neo4j 密码（默认从 .env 读取 NEO4J_PASSWORD）",
    )
    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help=f"CSV 数据目录（默认: {DEFAULT_DATA_DIR}）",
    )
    return parser.parse_args()


def main() -> None:
    """脚本主入口

    流程：
    1. 解析参数 + 加载 .env 配置
    2. 连接 Neo4j
    3. --force 模式下清空已有图谱
    4. 依次导入 Chapter、KnowledgePoint、BELONGS_TO、PREREQUISITE
    5. 输出统计信息
    """
    args = parse_args()

    # 加载 .env（低优先级）
    env_vars = load_dotenv(DOTENV_PATH)

    # 连接参数：CLI > .env > 默认值
    uri = args.uri or env_vars.get("NEO4J_URI", "bolt://localhost:7687")
    user = args.user or env_vars.get("NEO4J_USER", "neo4j")
    password = args.password or env_vars.get("NEO4J_PASSWORD", "")

    data_dir = Path(args.data_dir)

    logger.info("=" * 60)
    logger.info("知识图谱数据导入 Neo4j")
    logger.info("数据目录: %s", data_dir)
    logger.info("Neo4j URI: %s", uri)
    logger.info("=" * 60)

    # 连接 Neo4j
    try:
        driver = connect_neo4j(uri, user, password)
    except (ServiceUnavailable, Neo4jError) as e:
        logger.error("无法连接 Neo4j: %s", e)
        sys.exit(1)

    start_time = time.perf_counter()

    try:
        # --force：清空数据
        if args.force:
            clear_graph(driver)
        else:
            logger.info("非 --force 模式，保留已有数据（使用 MERGE 去重导入）")

        # 读取 CSV 文件
        chapters = read_csv(data_dir / "chapters.csv")
        kps = read_csv(data_dir / "knowledge_points.csv")
        prereqs = read_csv(data_dir / "prerequisites.csv")

        # 逐步导入
        import_chapters(driver, chapters)
        import_knowledge_points(driver, kps)
        import_belongs_to(driver, kps)

        prereq_count, cycles = import_prerequisites(driver, prereqs)

        # 输出统计
        elapsed = time.perf_counter() - start_time
        stats = query_graph_stats(driver)

        logger.info("=" * 60)
        logger.info("导入完成！耗时: %.2f 秒", elapsed)
        logger.info("  总节点数:       %d", stats["node_count"])
        logger.info("  Chapter:        %d", stats["chapter_count"])
        logger.info("  KnowledgePoint: %d", stats["kp_count"])
        logger.info("  BELONGS_TO:     %d", stats["belongs_to_count"])
        logger.info("  PREREQUISITE:   %d", stats["prereq_count"])
        if cycles:
            logger.warning("  警告：检测到 %d 个环，PREREQUISITE 关系未创建！", len(cycles))
        logger.info("=" * 60)

        if cycles:
            sys.exit(2)

    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:
        logger.exception("导入过程中发生异常: %s", e)
        sys.exit(1)
    finally:
        driver.close()
        logger.info("Neo4j 连接已关闭")


if __name__ == "__main__":
    main()
