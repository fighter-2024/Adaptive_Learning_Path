"""
知识点管理业务服务

负责知识点（KnowledgePoint）在 Neo4j 中的增删改查与前置依赖管理。
Service 层不接触 HTTP 对象，只处理业务数据；所有同步 Neo4j / SQL Server
操作通过 asyncio.to_thread 放入线程池执行，避免阻塞事件循环。

图谱模型（与 kg-data/scripts/import_knowledge_graph.py 保持一致）：
- 节点 KnowledgePoint: {id, name, description, chapter_id, difficulty,
  estimated_time, sort_order, created_at}
- 节点 Chapter: {id, name, sort_order}
- 关系 (KnowledgePoint)-[:BELONGS_TO]->(Chapter)
- 关系 (前置知识点)-[:PREREQUISITE]->(后继知识点)
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from app.db import get_driver
from app.models.knowledge_point import (
    KnowledgePointBrief,
    KnowledgePointDetail,
    KnowledgePointItem,
)

logger = logging.getLogger(__name__)

# ==================== 业务异常 ====================
# Router 层捕获这些异常并映射为统一响应码，不向客户端暴露内部堆栈。


class KnowledgePointNotFoundError(Exception):
    """知识点不存在"""

    def __init__(self, kp_id: str) -> None:
        self.kp_id = kp_id
        super().__init__(f"知识点 {kp_id} 不存在")


class ChapterNotFoundError(Exception):
    """章节不存在"""

    def __init__(self, chapter_id: str) -> None:
        self.chapter_id = chapter_id
        super().__init__(f"章节 {chapter_id} 不存在，请先创建章节")


class KnowledgePointDependencyError(Exception):
    """知识点被其他知识点依赖，无法删除"""

    def __init__(self, dependent_count: int) -> None:
        self.dependent_count = dependent_count
        super().__init__(f"该知识点被 {dependent_count} 个知识点依赖，无法删除")


class PrerequisiteValidationError(Exception):
    """前置依赖关系校验失败（前置不存在/自引用/存在环）"""


# ==================== 工具函数 ====================


def _generate_kp_id() -> str:
    """生成知识点业务 ID

    Returns:
        形如 kp_xxxxxxxx 的 ID（8 位十六进制，与 stu_/adm_ 风格一致）
    """
    return f"kp_{uuid.uuid4().hex[:8]}"


def sanitize_kp_list_row(row: dict) -> dict:
    """补齐 Neo4j 返回行的必填字段默认值（历史数据 null 容错）

    历史导入/手工创建的 KnowledgePoint 节点可能缺少 difficulty /
    estimated_time / chapter_id 等属性（Neo4j 返回 None），直接喂给
    KnowledgePointItem 会触发 Pydantic 校验失败 → 500。这里统一补默认值，
    与学员端 _db_list_student_kps 的兜底策略保持一致。

    Args:
        row: Neo4j 查询返回的行字典

    Returns:
        字段齐全的字典（缺属性补默认值）
    """
    return {
        "id": row.get("id") or "",
        "name": row.get("name") or "",
        "description": row.get("description") or "",
        "chapter_id": row.get("chapter_id") or "",
        "chapter_name": row.get("chapter_name"),
        "difficulty": row.get("difficulty")
        if row.get("difficulty") is not None
        else 0.0,
        "estimated_time": row.get("estimated_time")
        if row.get("estimated_time") is not None
        else 0,
        "prerequisite_count": row.get("prerequisite_count") or 0,
        "created_at": row.get("created_at"),
    }


def detect_cycles(edges: List[Tuple[str, str]]) -> List[List[str]]:
    """使用 DFS 检测前置依赖图中的环（三色标记法）

    Args:
        edges: (source, target) 边列表，source 是 target 的前置知识点

    Returns:
        检测到的所有环（每个环是一个节点 ID 列表）；空列表表示无环
    """
    adjacency: Dict[str, List[str]] = {}
    all_nodes: set = set()
    for src, tgt in edges:
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


# ==================== Neo4j 同步操作（线程池执行） ====================


def _db_query_page(
    page: int,
    page_size: int,
    chapter_id: Optional[str],
    keyword: Optional[str],
) -> Tuple[int, List[dict]]:
    """分页查询知识点（同步执行）

    按章节筛选（chapter_id）、按名称模糊搜索（keyword，大小写不敏感），
    返回总数和当前页行数据。prerequisite_count 由 Neo4j 拓扑统计。
    """
    skip = (page - 1) * page_size
    driver = get_driver()
    with driver.session() as session:
        total_record = session.run(
            """
            MATCH (k:KnowledgePoint)
            WHERE ($chapter_id IS NULL OR k.chapter_id = $chapter_id)
              AND ($keyword IS NULL OR toLower(k.name) CONTAINS toLower($keyword))
            RETURN count(k) AS total
            """,
            chapter_id=chapter_id,
            keyword=keyword,
        ).single()
        total = total_record["total"] if total_record else 0

        result = session.run(
            """
            MATCH (k:KnowledgePoint)
            WHERE ($chapter_id IS NULL OR k.chapter_id = $chapter_id)
              AND ($keyword IS NULL OR toLower(k.name) CONTAINS toLower($keyword))
            OPTIONAL MATCH (c:Chapter {id: k.chapter_id})
            OPTIONAL MATCH (pre:KnowledgePoint)-[:PREREQUISITE]->(k)
            WITH k, c, count(pre) AS prerequisite_count
            RETURN k.id AS id,
                   k.name AS name,
                   k.description AS description,
                   k.chapter_id AS chapter_id,
                   c.name AS chapter_name,
                   k.difficulty AS difficulty,
                   k.estimated_time AS estimated_time,
                   k.created_at AS created_at,
                   prerequisite_count
            ORDER BY c.sort_order, k.sort_order, k.id
            SKIP $skip LIMIT $limit
            """,
            chapter_id=chapter_id,
            keyword=keyword,
            skip=skip,
            limit=page_size,
        )
        rows = [sanitize_kp_list_row(dict(record)) for record in result]
    return total, rows


def _db_get_detail(kp_id: str) -> Optional[dict]:
    """查询单个知识点详情（同步执行）

    返回含 chapter_name、prerequisites（前置）、dependents（后继）的字典，
    知识点不存在时返回 None。
    """
    driver = get_driver()
    with driver.session() as session:
        record = session.run(
            """
            MATCH (k:KnowledgePoint {id: $id})
            OPTIONAL MATCH (c:Chapter {id: k.chapter_id})
            OPTIONAL MATCH (pre:KnowledgePoint)-[:PREREQUISITE]->(k)
            OPTIONAL MATCH (k)-[:PREREQUISITE]->(dep:KnowledgePoint)
            WITH k, c,
                 collect(DISTINCT pre) AS pres,
                 collect(DISTINCT dep) AS deps
            RETURN k,
                   c.name AS chapter_name,
                   [pre IN pres WHERE pre IS NOT NULL
                    | {id: pre.id, name: pre.name}] AS prerequisites,
                   [dep IN deps WHERE dep IS NOT NULL
                    | {id: dep.id, name: dep.name}] AS dependents
            """,
            id=kp_id,
        ).single()

    if record is None or record["k"] is None:
        return None

    node = record["k"]
    prerequisites = sorted(record["prerequisites"], key=lambda x: x["id"])
    dependents = sorted(record["dependents"], key=lambda x: x["id"])
    return {
        "id": node["id"],
        "name": node["name"],
        "description": node.get("description") or "",
        "chapter_id": node.get("chapter_id") or "",
        "chapter_name": record["chapter_name"],
        "difficulty": node.get("difficulty")
        if node.get("difficulty") is not None
        else 0.0,
        "estimated_time": node.get("estimated_time")
        if node.get("estimated_time") is not None
        else 0,
        "prerequisites": prerequisites,
        "dependents": dependents,
    }


def _normalize_prerequisite_ids(prerequisite_ids: Optional[List[str]]) -> List[str]:
    """去重并保留前置知识点的提交顺序。"""
    return list(dict.fromkeys(prerequisite_ids or []))


def _validate_prerequisites_in_tx(
    tx,
    kp_id: str,
    prerequisite_ids: List[str],
) -> None:
    """在当前 Neo4j 写事务内校验前置节点和环路。"""
    if kp_id in prerequisite_ids:
        raise PrerequisiteValidationError("知识点不能以自身为前置")

    if prerequisite_ids:
        found = tx.run(
            """
            MATCH (p:KnowledgePoint)
            WHERE p.id IN $ids
            RETURN collect(p.id) AS ids
            """,
            ids=prerequisite_ids,
        ).single()
        found_ids = set(found["ids"]) if found else set()
        missing = [pid for pid in prerequisite_ids if pid not in found_ids]
        if missing:
            raise PrerequisiteValidationError(
                "前置知识点不存在: " + ", ".join(missing)
            )

    edge_result = tx.run(
        """
        MATCH (source:KnowledgePoint)-[:PREREQUISITE]->(target:KnowledgePoint)
        RETURN source.id AS source, target.id AS target
        """
    )
    edges = [
        (record["source"], record["target"])
        for record in edge_result
        if record["target"] != kp_id
    ]
    edges.extend((pid, kp_id) for pid in prerequisite_ids)
    cycles = detect_cycles(edges)
    if cycles:
        cycle_desc = " → ".join(cycles[0])
        raise PrerequisiteValidationError(f"前置关系存在环: {cycle_desc}")


def _db_create(
    kp_id: str,
    name: str,
    description: str,
    chapter_id: str,
    difficulty: float,
    estimated_time: int,
    prerequisite_ids: Optional[List[str]] = None,
) -> dict:
    """创建知识点节点并建立 BELONGS_TO 关系（同步执行）

    整个创建过程在一个写事务内原子执行：
    若章节不存在则 MATCH 不产生行、CREATE 不执行。

    Raises:
        ChapterNotFoundError: 章节不存在
    """
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    normalized_prerequisite_ids = _normalize_prerequisite_ids(prerequisite_ids)
    driver = get_driver()

    def _do_create(tx) -> dict:
        record = tx.run(
            """
            MATCH (c:Chapter {id: $chapter_id})
            RETURN c.name AS chapter_name
            """,
            chapter_id=chapter_id,
        ).single()
        if record is None:
            raise ChapterNotFoundError(chapter_id)

        # 所有校验、节点创建和关系创建均在同一 execute_write 事务内。
        _validate_prerequisites_in_tx(tx, kp_id, normalized_prerequisite_ids)
        tx.run(
            """
            MATCH (c:Chapter {id: $chapter_id})
            CREATE (k:KnowledgePoint {
                id: $id, name: $name, description: $description,
                chapter_id: $chapter_id, difficulty: $difficulty,
                estimated_time: $estimated_time, sort_order: 0,
                created_at: $created_at
            })
            CREATE (k)-[:BELONGS_TO]->(c)
            """,
            id=kp_id,
            name=name,
            description=description,
            chapter_id=chapter_id,
            difficulty=difficulty,
            estimated_time=estimated_time,
            created_at=now,
        )
        if normalized_prerequisite_ids:
            tx.run(
                """
                MATCH (k:KnowledgePoint {id: $id})
                UNWIND $prerequisite_ids AS prerequisite_id
                MATCH (pre:KnowledgePoint {id: prerequisite_id})
                CREATE (pre)-[:PREREQUISITE]->(k)
                """,
                id=kp_id,
                prerequisite_ids=normalized_prerequisite_ids,
            )
        return {
            "id": kp_id,
            "name": name,
            "description": description,
            "chapter_id": chapter_id,
            "chapter_name": record["chapter_name"],
            "difficulty": difficulty,
            "estimated_time": estimated_time,
            "prerequisite_count": len(normalized_prerequisite_ids),
            "question_count": 0,
            "created_at": now,
        }

    with driver.session() as session:
        return session.execute_write(_do_create)


def _db_update(
    kp_id: str,
    name: str,
    description: str,
    chapter_id: str,
    difficulty: float,
    estimated_time: int,
    prerequisite_ids: Optional[List[str]] = None,
) -> Optional[dict]:
    """更新知识点属性并重建 BELONGS_TO 关系（同步执行）

    Returns:
        更新后的知识点数据（列表项结构）；知识点不存在时返回 None

    Raises:
        ChapterNotFoundError: 目标章节不存在
    """
    normalized_prerequisite_ids = (
        None
        if prerequisite_ids is None
        else _normalize_prerequisite_ids(prerequisite_ids)
    )
    driver = get_driver()

    def _do_update(tx) -> Optional[dict]:
        exists = tx.run(
            "MATCH (k:KnowledgePoint {id: $id}) RETURN k.id AS id", id=kp_id
        ).single()
        if exists is None:
            return None

        chapter = tx.run(
            "MATCH (c:Chapter {id: $id}) RETURN c.name AS name", id=chapter_id
        ).single()
        if chapter is None:
            raise ChapterNotFoundError(chapter_id)

        # 在修改节点属性前完成关系校验，失败时 execute_write 自动回滚。
        # PUT 未携带 prerequisite_ids 时保留历史关系，兼容旧调用方。
        if normalized_prerequisite_ids is not None:
            _validate_prerequisites_in_tx(tx, kp_id, normalized_prerequisite_ids)

        tx.run(
            """
            MATCH (k:KnowledgePoint {id: $id})
            SET k.name = $name,
                k.description = $description,
                k.chapter_id = $chapter_id,
                k.difficulty = $difficulty,
                k.estimated_time = $estimated_time
            WITH k
            OPTIONAL MATCH (k)-[r:BELONGS_TO]->(:Chapter)
            DELETE r
            WITH k
            MATCH (c:Chapter {id: $chapter_id})
            MERGE (k)-[:BELONGS_TO]->(c)
            """,
            id=kp_id,
            name=name,
            description=description,
            chapter_id=chapter_id,
            difficulty=difficulty,
            estimated_time=estimated_time,
        )
        if normalized_prerequisite_ids is not None:
            tx.run(
                """
                MATCH (k:KnowledgePoint {id: $id})
                OPTIONAL MATCH (pre:KnowledgePoint)-[r:PREREQUISITE]->(k)
                DELETE r
                """,
                id=kp_id,
            )
        if normalized_prerequisite_ids:
            tx.run(
                """
                MATCH (k:KnowledgePoint {id: $id})
                UNWIND $prerequisite_ids AS prerequisite_id
                MATCH (pre:KnowledgePoint {id: prerequisite_id})
                CREATE (pre)-[:PREREQUISITE]->(k)
                """,
                id=kp_id,
                prerequisite_ids=normalized_prerequisite_ids,
            )
        record = tx.run(
            """
            MATCH (k:KnowledgePoint {id: $id})
            MATCH (c:Chapter {id: k.chapter_id})
            OPTIONAL MATCH (pre:KnowledgePoint)-[:PREREQUISITE]->(k)
            RETURN c.name AS chapter_name,
                   k.created_at AS created_at,
                   count(pre) AS prerequisite_count
            """,
            id=kp_id,
        ).single()

        return {
            "id": kp_id,
            "name": name,
            "description": description,
            "chapter_id": chapter_id,
            "chapter_name": record["chapter_name"],
            "difficulty": difficulty,
            "estimated_time": estimated_time,
            "prerequisite_count": record["prerequisite_count"],
            "question_count": 0,
            "created_at": record["created_at"],
        }

    with driver.session() as session:
        return session.execute_write(_do_update)


def _db_delete(kp_id: str) -> None:
    """删除知识点节点及其所有关系（同步执行）

    删除前检查是否有其他知识点依赖它（该知识点作为前置被引用），
    有依赖则拒绝删除。

    Raises:
        KnowledgePointNotFoundError: 知识点不存在
        KnowledgePointDependencyError: 被其他知识点依赖
    """
    driver = get_driver()

    def _do_delete(tx) -> None:
        record = tx.run(
            """
            MATCH (k:KnowledgePoint {id: $id})
            OPTIONAL MATCH (k)-[:PREREQUISITE]->(dep:KnowledgePoint)
            RETURN k.id AS id, count(dep) AS dependent_count
            """,
            id=kp_id,
        ).single()
        if record is None or record["id"] is None:
            raise KnowledgePointNotFoundError(kp_id)
        if record["dependent_count"] > 0:
            raise KnowledgePointDependencyError(record["dependent_count"])

        tx.run(
            "MATCH (k:KnowledgePoint {id: $id}) DETACH DELETE k",
            id=kp_id,
        )

    with driver.session() as session:
        session.execute_write(_do_delete)


def _db_replace_prerequisites(kp_id: str, prerequisite_ids: List[str]) -> None:
    """全量替换知识点的前置依赖（同步执行）

    校验通过后删除该知识点所有旧的前置关系，按新列表重建。
    整个流程在一个写事务内原子执行，校验失败自动回滚。

    Raises:
        KnowledgePointNotFoundError: 知识点不存在
        PrerequisiteValidationError: 前置知识点不存在/自引用/替换后图中存在环
    """
    driver = get_driver()

    def _do_replace(tx) -> None:
        # 1. 目标知识点必须存在
        exists = tx.run(
            "MATCH (k:KnowledgePoint {id: $id}) RETURN k.id AS id", id=kp_id
        ).single()
        if exists is None:
            raise KnowledgePointNotFoundError(kp_id)

        # 2. 前置知识点必须全部存在
        if prerequisite_ids:
            found = tx.run(
                """
                MATCH (p:KnowledgePoint)
                WHERE p.id IN $ids
                RETURN collect(p.id) AS ids
                """,
                ids=prerequisite_ids,
            ).single()
            found_ids = set(found["ids"]) if found else set()
            missing = [pid for pid in prerequisite_ids if pid not in found_ids]
            if missing:
                raise PrerequisiteValidationError(
                    "前置知识点不存在: " + ", ".join(missing)
                )

        # 3. 不允许以自身为前置
        if kp_id in prerequisite_ids:
            raise PrerequisiteValidationError("知识点不能以自身为前置")

        # 4. 环检测：现有边（排除指向目标知识点的旧入边）+ 新入边
        edge_result = tx.run(
            """
            MATCH (s:KnowledgePoint)-[:PREREQUISITE]->(t:KnowledgePoint)
            RETURN s.id AS source, t.id AS target
            """
        )
        edges = [
            (record["source"], record["target"])
            for record in edge_result
            if record["target"] != kp_id
        ]
        edges.extend((pid, kp_id) for pid in prerequisite_ids)
        cycles = detect_cycles(edges)
        if cycles:
            cycle_desc = " → ".join(cycles[0])
            raise PrerequisiteValidationError(f"前置关系存在环: {cycle_desc}")

        # 5. 删除旧入边，创建新入边（全量替换）
        tx.run(
            """
            MATCH (k:KnowledgePoint {id: $id})
            OPTIONAL MATCH (pre:KnowledgePoint)-[r:PREREQUISITE]->(k)
            DELETE r
            WITH k
            UNWIND $prereq_ids AS pid
            MATCH (p:KnowledgePoint {id: pid})
            CREATE (p)-[:PREREQUISITE]->(k)
            """,
            id=kp_id,
            prereq_ids=prerequisite_ids,
        )

    with driver.session() as session:
        session.execute_write(_do_replace)


# ==================== SQL Server 统计（线程池执行） ====================


def _query_question_counts(kp_ids: List[str]) -> Dict[str, int]:
    """从 SQL Server 批量查询知识点关联题目数（同步执行）

    题目-知识点映射存于 SQL Server 的 q_matrix 表（总则职责划分），
    这里仅做聚合统计，不涉及图谱拓扑。

    Args:
        kp_ids: 知识点 ID 列表

    Returns:
        {knowledge_point_id: 题目数}
    """
    if not kp_ids:
        return {}
    # 延迟导入避免模块循环依赖
    from app.db.sqlserver import get_connection

    placeholders = ", ".join(["?"] * len(kp_ids))
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT knowledge_point_id, COUNT(1) AS cnt FROM q_matrix "
            f"WHERE knowledge_point_id IN ({placeholders}) "
            f"GROUP BY knowledge_point_id",
            tuple(kp_ids),
        )
        return {row[0]: int(row[1]) for row in cursor.fetchall()}
    finally:
        conn.close()


# ==================== 异步服务接口 ====================


async def list_knowledge_points(
    page: int = 1,
    page_size: int = 20,
    chapter_id: Optional[str] = None,
    keyword: Optional[str] = None,
) -> Tuple[List[KnowledgePointItem], int]:
    """分页查询知识点列表

    Args:
        page: 页码，从 1 开始
        page_size: 每页条数
        chapter_id: 按章节筛选，None 表示不过滤
        keyword: 按名称模糊搜索（大小写不敏感），None 表示不过滤

    Returns:
        (当前页知识点列表, 总数)

    Note:
        question_count 来自 SQL Server；SQL Server 不可用时降级为 0
        并记录 warning 日志，不阻塞列表查询。
    """
    total, rows = await asyncio.to_thread(
        _db_query_page, page, page_size, chapter_id, keyword
    )

    # 批量查询关联题目数（SQL Server），失败降级为 0
    question_counts: Dict[str, int] = {}
    try:
        question_counts = await asyncio.to_thread(
            _query_question_counts, [row["id"] for row in rows]
        )
    except Exception as e:
        logger.warning("查询知识点关联题目数失败，question_count 降级为 0: %s", e)

    items = [
        KnowledgePointItem(
            **{**row, "question_count": question_counts.get(row["id"], 0)}
        )
        for row in rows
    ]
    return items, total


async def get_knowledge_point(kp_id: str) -> Optional[KnowledgePointDetail]:
    """查询单个知识点详情（含前置/后继知识点）

    Args:
        kp_id: 知识点 ID

    Returns:
        KnowledgePointDetail 或 None（知识点不存在）
    """
    data = await asyncio.to_thread(_db_get_detail, kp_id)
    if data is None:
        return None
    return KnowledgePointDetail(**data)


async def create_knowledge_point(
    name: str,
    description: str,
    chapter_id: str,
    difficulty: float,
    estimated_time: int,
    prerequisite_ids: Optional[List[str]] = None,
) -> KnowledgePointItem:
    """新增知识点

    Args:
        name: 知识点名称
        description: 知识点描述
        chapter_id: 所属章节 ID（必须已存在于 Neo4j）
        difficulty: 难度系数 0.0~1.0
        estimated_time: 预估学习时长（分钟）

    Returns:
        创建后的知识点（列表项结构，含新生成的 id）

    Raises:
        ChapterNotFoundError: 章节不存在
    """
    kp_id = _generate_kp_id()
    data = await asyncio.to_thread(
        _db_create,
        kp_id,
        name,
        description,
        chapter_id,
        difficulty,
        estimated_time,
        prerequisite_ids,
    )
    logger.info("知识点创建成功: %s (%s)", kp_id, name)
    return KnowledgePointItem(**data)


async def update_knowledge_point(
    kp_id: str,
    name: str,
    description: str,
    chapter_id: str,
    difficulty: float,
    estimated_time: int,
    prerequisite_ids: Optional[List[str]] = None,
) -> Optional[KnowledgePointItem]:
    """编辑知识点

    Args:
        kp_id: 知识点 ID
        name: 新名称
        description: 新描述
        chapter_id: 新章节 ID
        difficulty: 新难度系数
        estimated_time: 新预估学习时长

    Returns:
        更新后的知识点（列表项结构）或 None（知识点不存在）

    Raises:
        ChapterNotFoundError: 目标章节不存在
    """
    data = await asyncio.to_thread(
        _db_update,
        kp_id,
        name,
        description,
        chapter_id,
        difficulty,
        estimated_time,
        prerequisite_ids,
    )
    if data is None:
        return None

    # 查询真实关联题目数（SQL Server），失败降级为 0
    try:
        counts = await asyncio.to_thread(_query_question_counts, [kp_id])
        data["question_count"] = counts.get(kp_id, 0)
    except Exception as e:
        logger.warning("查询知识点关联题目数失败，question_count 降级为 0: %s", e)

    logger.info("知识点更新成功: %s", kp_id)
    return KnowledgePointItem(**data)


async def delete_knowledge_point(kp_id: str) -> None:
    """删除知识点

    删除前检查是否有其他知识点依赖它，有依赖则拒绝删除。

    Args:
        kp_id: 知识点 ID

    Raises:
        KnowledgePointNotFoundError: 知识点不存在
        KnowledgePointDependencyError: 被其他知识点依赖
    """
    await asyncio.to_thread(_db_delete, kp_id)
    logger.info("知识点删除成功: %s", kp_id)


async def replace_prerequisites(
    kp_id: str, prerequisite_ids: List[str]
) -> KnowledgePointDetail:
    """全量替换知识点的前置依赖

    Args:
        kp_id: 知识点 ID
        prerequisite_ids: 新的前置知识点 ID 列表（传什么就是什么，不追加）

    Returns:
        替换后的知识点详情（含新的前置/后继列表）

    Raises:
        KnowledgePointNotFoundError: 知识点不存在
        PrerequisiteValidationError: 前置知识点不存在/自引用/存在环
    """
    await asyncio.to_thread(_db_replace_prerequisites, kp_id, prerequisite_ids)
    logger.info("前置依赖替换成功: %s -> %s", kp_id, prerequisite_ids)

    data = await asyncio.to_thread(_db_get_detail, kp_id)
    if data is None:
        raise KnowledgePointNotFoundError(kp_id)
    return KnowledgePointDetail(**data)
