"""
知识图谱查询服务。

Neo4j 只负责图拓扑，SQL Server 只负责学生掌握快照。图谱查询先在
Neo4j 中确定候选节点，再用一次 IN 查询批量读取掌握度，最后由 service
合并标准节点、边和推荐信息。Service 不接触 HTTP 对象。
"""

import asyncio
import logging
from typing import Dict, List, Optional, Sequence, Tuple

from neo4j.exceptions import DriverError, Neo4jError

from app.db import get_driver
from app.models.graph import GraphData, GraphEdge, GraphMeta, GraphNode, GraphView
from app.services.learning_path_service import (
    MASTERED_THRESHOLD,
    KnowledgeGraphCycleError,
    compute_distances_to_target,
    greedy_select_path,
    topological_sort,
)
from app.services.student_knowledge_point_service import compute_mastery_status

logger = logging.getLogger(__name__)

COURSE_ROOT_ID = "course_root"
COURSE_ROOT_LABEL = "课程总览"
GRAPH_ALGORITHM_VERSION = "greedy-v1"
GRAPH_WEIGHT_PROFILE = "default-v1"


class GraphFocusNotFoundError(Exception):
    """请求聚焦的知识点不存在。"""


class GraphNeo4jError(Exception):
    """图谱读取失败，供 router 映射为 50002。"""


class GraphSqlServerError(Exception):
    """学生掌握度读取失败，供 router 映射为 50001。"""


class CandidateSelection(list[str]):
    """Neo4j 已完成计数和有界排序后的候选 ID 集合。

    列表本身只保留要继续读取属性的有限 ID；总数和章节数由 Neo4j 在同一
    查询中计算，避免把全图节点属性或全量 ID 拉回 Python。
    """

    def __init__(
        self,
        ids: Sequence[str],
        total_count: int,
        chapter_count: int,
    ) -> None:
        super().__init__(ids)
        self.total_count = total_count
        self.chapter_count = chapter_count


def _as_list(value: object) -> List[dict]:
    """将 Neo4j 返回的列表安全转换为字典列表。"""
    if not value:
        return []
    return [dict(item) for item in value if item is not None]


def _db_focus_exists(focus_id: str) -> bool:
    """检查聚焦知识点是否存在。"""
    driver = get_driver()
    with driver.session() as session:
        record = session.run(
            "MATCH (k:KnowledgePoint {id: $focus_id}) RETURN k.id AS id",
            focus_id=focus_id,
        ).single()
    return record is not None and record["id"] is not None


def _db_query_candidate_ids(
    focus_id: Optional[str],
    depth: int,
    chapter_id: Optional[str] = None,
    keyword: Optional[str] = None,
    direction: str = "both",
    excluded_ids: Optional[Sequence[str]] = None,
    limit: int = 500,
) -> CandidateSelection:
    """在 Neo4j 内完成候选计数、排序和有界 ID 选择。

    只将最多 ``limit`` 个 ID 返回给 Python；属性读取在后续查询中继续受
    该集合约束。``excluded_ids`` 用于 ``include_mastered=false``，其来源
    是 SQL Server 按用户索引读取的已掌握 ID，而不是全量掌握度参数列表。
    """
    excluded = list(excluded_ids or [])
    base_filter = """
        ($chapter_id IS NULL
         OR k.chapter_id = $chapter_id
         OR EXISTS {
             MATCH (k)-[:BELONGS_TO]->(:Chapter {id: $chapter_id})
         })
        AND ($keyword IS NULL
             OR toLower(coalesce(k.name, '')) CONTAINS toLower($keyword))
    """
    exclusion_filter = """
        AND (size($excluded_ids) = 0
             OR k.id = $focus_id
             OR NOT k.id IN $excluded_ids)
    """

    if focus_id is None:
        match_body = "MATCH (k:KnowledgePoint)"
        where_clause = f"WHERE {base_filter}{exclusion_filter}"
        order_clause = "k.id"
    else:
        if direction == "incoming":
            path_pattern = "(k)-[:PREREQUISITE*0..3]->(focus)"
        elif direction == "outgoing":
            path_pattern = "(focus)-[:PREREQUISITE*0..3]->(k)"
        else:
            path_pattern = "(focus)-[:PREREQUISITE*0..3]-(k)"
        match_body = f"""
            MATCH (focus:KnowledgePoint {{id: $focus_id}})
            MATCH path={path_pattern}
            WITH k, min(length(path)) AS distance
        """
        where_clause = f"""
            WHERE distance <= $depth
              AND (k.id = $focus_id OR ({base_filter}))
              {exclusion_filter}
        """
        order_clause = "distance, k.id"

    query = f"""
        CALL () {{
            {match_body}
            {where_clause}
            RETURN count(DISTINCT k) AS total_count
        }}
        CALL () {{
            {match_body}
            {where_clause}
            OPTIONAL MATCH (k)-[:BELONGS_TO]->(chapter:Chapter)
            RETURN count(DISTINCT chapter) AS chapter_count
        }}
        CALL () {{
            {match_body}
            {where_clause}
            RETURN k.id AS id
            ORDER BY {order_clause}
            LIMIT $limit
        }}
        RETURN total_count, chapter_count, collect(id) AS ids
    """
    params = {
        "focus_id": focus_id,
        "depth": depth,
        "chapter_id": chapter_id,
        "keyword": keyword,
        "excluded_ids": excluded,
        "limit": limit,
    }

    driver = get_driver()
    with driver.session() as session:
        record = session.run(query, **params).single()
    if record is None:
        return CandidateSelection([], 0, 0)
    return CandidateSelection(
        [kp_id for kp_id in record["ids"] if kp_id is not None],
        int(record["total_count"] or 0),
        int(record["chapter_count"] or 0),
    )


def _db_load_graph_rows(node_ids: Sequence[str]) -> dict:
    """读取渲染节点、直接前置语义，并在 Neo4j 侧检测相关环路。

    ``external_knowledge_points`` 是“直接前置但未进入渲染窗口”的拓扑
    节点，仅供 locked 和推荐算法使用，不会突破 max_nodes 被展示出来。
    环检测单独只返回节点 ID 路径，避免把完整图谱属性拉回 Python。
    """
    empty_rows = {
        "knowledge_points": [],
        "external_knowledge_points": [],
        "chapters": [],
        "prerequisites": [],
        "cycle_path": [],
    }
    if not node_ids:
        return empty_rows

    driver = get_driver()
    with driver.session() as session:
        record = session.run(
            """
            CALL () {
                MATCH (k:KnowledgePoint)
                WHERE k.id IN $node_ids
                OPTIONAL MATCH (k)-[:BELONGS_TO]->(c:Chapter)
                RETURN collect(DISTINCT {
                           id: k.id,
                           name: k.name,
                           chapter_id: coalesce(k.chapter_id, c.id),
                           difficulty: k.difficulty,
                           estimated_time: k.estimated_time
                       }) AS knowledge_points,
                       [x IN collect(DISTINCT CASE WHEN c IS NULL THEN NULL ELSE {
                           id: c.id, name: c.name
                       } END) WHERE x IS NOT NULL] AS chapters
            }
            CALL () {
                MATCH (target:KnowledgePoint)
                WHERE target.id IN $node_ids
                OPTIONAL MATCH (source:KnowledgePoint)-[:PREREQUISITE]->(target)
                RETURN [x IN collect(DISTINCT CASE WHEN source IS NULL THEN NULL ELSE {
                           source: source.id,
                           target: target.id,
                           id: 'pre_' + source.id + '_' + target.id
                       } END) WHERE x IS NOT NULL] AS prerequisites,
                       [x IN collect(DISTINCT source.id) WHERE x IS NOT NULL]
                           AS external_ids
            }
            CALL (external_ids) {
                WITH external_ids
                OPTIONAL MATCH (external:KnowledgePoint)
                WHERE external.id IN external_ids
                OPTIONAL MATCH (external)-[:BELONGS_TO]->(external_chapter:Chapter)
                RETURN [x IN collect(DISTINCT CASE WHEN external IS NULL THEN NULL ELSE {
                           id: external.id,
                           name: external.name,
                           chapter_id: coalesce(external.chapter_id, external_chapter.id),
                           difficulty: external.difficulty,
                           estimated_time: external.estimated_time
                       } END) WHERE x IS NOT NULL] AS external_knowledge_points
            }
            RETURN knowledge_points, external_knowledge_points, chapters, prerequisites
            """,
            node_ids=list(node_ids),
        ).single()

        cycle_record = session.run(
            """
            MATCH (anchor:KnowledgePoint)
            WHERE anchor.id IN $node_ids
            MATCH cycle=(anchor)-[:PREREQUISITE*1..]->(anchor)
            RETURN [node IN nodes(cycle) | node.id] AS cycle_path
            LIMIT 1
            """,
            node_ids=list(node_ids),
        ).single()

    cycle_path = (
        list(cycle_record["cycle_path"] or [])
        if cycle_record is not None
        else []
    )
    if record is None:
        empty_rows["cycle_path"] = cycle_path
        return empty_rows
    return {
        "knowledge_points": _as_list(record["knowledge_points"]),
        "external_knowledge_points": _as_list(record["external_knowledge_points"]),
        "chapters": _as_list(record["chapters"]),
        "prerequisites": _as_list(record["prerequisites"]),
        "cycle_path": cycle_path,
    }


def _db_query_chapter_ids(node_ids: Sequence[str]) -> List[str]:
    """批量统计候选知识点关联的章节 ID，用于准确计算 total_nodes。"""
    if not node_ids:
        return []
    driver = get_driver()
    with driver.session() as session:
        record = session.run(
            """
            MATCH (k:KnowledgePoint)
            WHERE k.id IN $node_ids
            OPTIONAL MATCH (k)-[:BELONGS_TO]->(c:Chapter)
            WITH DISTINCT coalesce(k.chapter_id, c.id) AS chapter_id
            RETURN collect(chapter_id) AS chapter_ids
            """,
            node_ids=list(node_ids),
        ).single()
    if record is None:
        return []
    return sorted(str(chapter_id) for chapter_id in record["chapter_ids"] if chapter_id)


SQL_BATCH_SIZE = 900


def _db_query_mastered_ids(user_id: str) -> set[str]:
    """按用户索引批量读取已掌握 ID，供 Neo4j 做服务端排除。"""
    from app.db.sqlserver import get_connection

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT knowledge_point_id FROM user_kp_mastery "
            "WHERE user_id = ? AND mastery_probability >= ?",
            (user_id, MASTERED_THRESHOLD),
        )
        mastered_ids = {str(row[0]) for row in cursor.fetchall()}
        logger.info(
            "图谱已掌握 ID 批量查询完成: user_id=%s count=%d",
            user_id,
            len(mastered_ids),
        )
        return mastered_ids
    finally:
        conn.close()


def _db_query_mastery_map(user_id: str, kp_ids: Sequence[str]) -> Dict[str, float]:
    """分批读取掌握度；每批是集合查询，不按节点逐条查询。"""
    if not kp_ids:
        return {}
    from app.db.sqlserver import get_connection

    conn = get_connection()
    try:
        cursor = conn.cursor()
        mastery_map: Dict[str, float] = {}
        batch_count = 0
        for offset in range(0, len(kp_ids), SQL_BATCH_SIZE):
            batch = list(kp_ids[offset : offset + SQL_BATCH_SIZE])
            placeholders = ", ".join("?" for _ in batch)
            cursor.execute(
                "SELECT knowledge_point_id, mastery_probability "
                "FROM user_kp_mastery "
                f"WHERE user_id = ? AND knowledge_point_id IN ({placeholders})",
                (user_id, *batch),
            )
            mastery_map.update(
                {str(row[0]): float(row[1]) for row in cursor.fetchall()}
            )
            batch_count += 1
        logger.info(
            "图谱掌握度批量查询完成: user_id=%s ids=%d batches=%d",
            user_id,
            len(kp_ids),
            batch_count,
        )
        return mastery_map
    finally:
        conn.close()


def _safe_float(value: object, default: float = 0.0) -> float:
    """将历史图谱中可能缺失的浮点属性规范化。"""
    return float(value) if value is not None else default


def _safe_int(value: object, default: int = 0) -> int:
    """将历史图谱中可能缺失的整数属性规范化。"""
    return int(value) if value is not None else default


def _select_render_ids(
    candidate_ids: Sequence[str], focus_id: Optional[str], max_nodes: int
) -> List[str]:
    """保留 Neo4j 的距离排序，同时强制 focus 位于渲染集合内。"""
    ordered = list(dict.fromkeys(candidate_ids))
    if focus_id is not None and focus_id in ordered:
        ordered = [focus_id, *[kp_id for kp_id in ordered if kp_id != focus_id]]
    return ordered[:max_nodes]


def _build_topology(
    knowledge_points: Sequence[dict], prerequisites: Sequence[dict]
) -> Tuple[Dict[str, dict], Dict[str, List[str]]]:
    """把 GraphData 行转换成现有路径算法所需的局部拓扑。"""
    topology: Dict[str, dict] = {
        row["id"]: {
            "name": row.get("name") or row["id"],
            "difficulty": _safe_float(row.get("difficulty")),
            "estimated_time": _safe_int(row.get("estimated_time")),
            "successors": [],
        }
        for row in knowledge_points
    }
    prereqs_map: Dict[str, List[str]] = {kp_id: [] for kp_id in topology}
    for edge in prerequisites:
        source = edge.get("source")
        target = edge.get("target")
        if source in topology and target in topology:
            topology[source]["successors"].append(target)
            prereqs_map[target].append(source)
    return topology, prereqs_map


def _build_recommendation_map(
    knowledge_points: Sequence[dict],
    prerequisites: Sequence[dict],
    mastery_map: Dict[str, float],
    focus_id: Optional[str],
    rendered_ids: Optional[set[str]] = None,
) -> Tuple[Dict[str, dict], set[Tuple[str, str]]]:
    """复用现有路径贪心算法，生成节点推荐字段和推荐边集合。"""
    topology, prereqs_map = _build_topology(knowledge_points, prerequisites)
    all_ids = list(topology)
    candidate_ids = [
        kp_id
        for kp_id in all_ids
        if mastery_map.get(kp_id) is None
        or mastery_map[kp_id] < MASTERED_THRESHOLD
    ]
    candidate_set = set(candidate_ids)
    candidate_edges = [
        (kp_id, successor)
        for kp_id in candidate_ids
        for successor in topology[kp_id]["successors"]
        if successor in candidate_set
    ]
    ordered_candidates = topological_sort(candidate_ids, candidate_edges)
    distance_map = (
        compute_distances_to_target(focus_id, prereqs_map)
        if focus_id in topology
        else None
    )
    if distance_map is not None:
        ordered_candidates = [
            kp_id for kp_id in ordered_candidates if kp_id in distance_map
        ]
    target_name = topology[focus_id]["name"] if focus_id in topology else None
    raw_steps = greedy_select_path(
        candidates=ordered_candidates,
        prereqs_map=prereqs_map,
        mastery_map=mastery_map,
        node_attrs=topology,
        dist_map=distance_map,
        target_id=focus_id if focus_id in topology else None,
        target_name=target_name,
        count=max(len(ordered_candidates), 1),
    )
    rendered_ids = rendered_ids or {row["id"] for row in knowledge_points}
    raw_ids = {step["id"] for step in raw_steps}

    def _can_recommend(kp_id: str, visiting: set[str]) -> bool:
        """确保渲染窗口外的未掌握前置不会被推荐结果隐式跳过。"""
        if kp_id in visiting:
            return False
        visiting.add(kp_id)
        for prerequisite in prereqs_map.get(kp_id, []):
            if mastery_map.get(prerequisite, 0.0) >= MASTERED_THRESHOLD:
                continue
            if prerequisite not in rendered_ids or prerequisite not in raw_ids:
                return False
            if not _can_recommend(prerequisite, visiting.copy()):
                return False
        return True

    recommendation_map = {
        step["id"]: {
            "order": step["order"],
            "reason": step["reason"],
        }
        for step in raw_steps
        if step["id"] in rendered_ids and _can_recommend(step["id"], set())
    }
    recommendation_edges = {
        (left["id"], right["id"])
        for left, right in zip(raw_steps, raw_steps[1:])
        if left["id"] in recommendation_map
        and right["id"] in recommendation_map
        and right["id"] in topology[left["id"]]["successors"]
    }
    return recommendation_map, recommendation_edges


def _build_graph_data(
    rows: dict,
    selected_ids: Sequence[str],
    total_knowledge_points: int,
    max_nodes: int,
    view: GraphView,
    focus_id: Optional[str],
    mastery_map: Dict[str, float],
    is_student: bool,
    total_chapters: Optional[int] = None,
) -> GraphData:
    """把数据库行组装为统一 GraphData，并严格执行返回节点上限。"""
    selected_set = set(selected_ids)
    rendered_by_id = {
        row["id"]: row
        for row in rows["knowledge_points"]
        if row.get("id") in selected_set
    }
    # 保持 Neo4j 的距离排序；MATCH ... IN 不保证返回顺序，不能重新按 ID 排。
    kps = [rendered_by_id[kp_id] for kp_id in selected_ids if kp_id in rendered_by_id]
    external_kps = [
        row
        for row in rows.get("external_knowledge_points", [])
        if row.get("id") not in selected_set
    ]
    topology_kps = [*kps, *external_kps]
    topology_ids = {row["id"] for row in topology_kps}
    chapters = [row for row in rows["chapters"] if row.get("id")]
    chapter_ids = {row["id"] for row in chapters}
    prerequisites = [
        edge
        for edge in rows["prerequisites"]
        if edge.get("source") in topology_ids and edge.get("target") in selected_set
    ]

    recommendation_map: Dict[str, dict] = {}
    recommendation_edges: set[Tuple[str, str]] = set()
    if view == "personalized":
        recommendation_map, recommendation_edges = _build_recommendation_map(
            topology_kps,
            prerequisites,
            mastery_map,
            focus_id,
            rendered_ids=set(row["id"] for row in kps),
        )

    # 先构造知识点和结构节点，再按 max_nodes 保留稳定前缀。这样即使
    # 存在 500 个模拟知识点，返回数组仍严格不超过契约上限。
    course_node = GraphNode(id=COURSE_ROOT_ID, label=COURSE_ROOT_LABEL, node_type="course")
    focus_chapter_id = next(
        (
            row.get("chapter_id")
            for row in kps
            if row.get("id") == focus_id and row.get("chapter_id") in chapter_ids
        ),
        None,
    )
    chapter_nodes = [
        GraphNode(id=row["id"], label=row.get("name") or row["id"], node_type="chapter")
        for row in sorted(
            chapters,
            key=lambda row: (0 if row["id"] == focus_chapter_id else 1, row["id"]),
        )
    ]
    kp_nodes = []
    kp_name_by_id = {
        row["id"]: row.get("name") or row["id"] for row in topology_kps
    }
    for row in kps:
        kp_id = row["id"]
        probability = mastery_map.get(kp_id)
        pending_prerequisites = [
            kp_name_by_id.get(edge.get("source"), edge.get("source"))
            for edge in prerequisites
            if edge.get("target") == kp_id
            if mastery_map.get(edge.get("source")) is None
            or mastery_map.get(edge.get("source"), 0.0) < MASTERED_THRESHOLD
        ]
        recommendation = recommendation_map.get(kp_id)
        locked = bool(pending_prerequisites)
        kp_nodes.append(
            GraphNode(
                id=kp_id,
                label=row.get("name") or kp_id,
                node_type="knowledge_point",
                chapter_id=row.get("chapter_id"),
                difficulty=_safe_float(row.get("difficulty")),
                estimated_time=_safe_int(row.get("estimated_time")),
                mastery_probability=probability,
                status=compute_mastery_status(probability) if is_student else None,
                locked=locked if is_student else None,
                recommend_order=(
                    recommendation["order"] if recommendation and is_student else None
                ),
                reason=(
                    recommendation["reason"] if recommendation and is_student else None
                ),
                tags=[],
            )
        )

    all_nodes = [course_node, *chapter_nodes, *kp_nodes] if kp_nodes else []
    if len(all_nodes) > max_nodes:
        # 图谱结构节点优先，但 max_nodes=1 时必须至少返回一个知识点；
        # 这个裁剪只影响展示，不改变 total_nodes/truncated 的统计。
        all_nodes = kp_nodes[:max_nodes]
        if max_nodes >= 2 and kp_nodes:
            all_nodes = [course_node, *kp_nodes[: max_nodes - 1]]
        if max_nodes >= 3 and kp_nodes and chapter_nodes:
            kp_limit = max_nodes - 1 - min(len(chapter_nodes), max_nodes - 2)
            all_nodes = [course_node, *chapter_nodes[: max_nodes - 1 - kp_limit], *kp_nodes[:kp_limit]]

    returned_ids = {node.id for node in all_nodes}
    edges: List[GraphEdge] = []
    for node in all_nodes:
        if node.node_type == "knowledge_point" and node.chapter_id in chapter_ids:
            edges.append(
                GraphEdge(
                    id=f"belongs_{node.id}_{node.chapter_id}",
                    source=node.id,
                    target=node.chapter_id,
                    relation="belongs_to",
                )
            )
    if COURSE_ROOT_ID in returned_ids:
        for chapter in chapter_nodes:
            if chapter.id in returned_ids:
                edges.append(
                    GraphEdge(
                        id=f"belongs_{chapter.id}_{COURSE_ROOT_ID}",
                        source=chapter.id,
                        target=COURSE_ROOT_ID,
                        relation="belongs_to",
                    )
                )
    for edge in prerequisites:
        if edge.get("source") in returned_ids and edge.get("target") in returned_ids:
            source = edge["source"]
            target = edge["target"]
            edges.append(
                GraphEdge(
                    id=edge.get("id") or f"pre_{source}_{target}",
                    source=source,
                    target=target,
                    relation="prerequisite",
                    recommended=(source, target) in recommendation_edges,
                )
            )

    complete_structural_count = (
        (total_chapters if total_chapters is not None else len(chapter_ids))
        + (1 if total_knowledge_points else 0)
    )
    total_nodes = total_knowledge_points + complete_structural_count
    return GraphData(
        nodes=all_nodes,
        edges=edges,
        meta=GraphMeta(
            view=view,
            focus_id=focus_id,
            total_nodes=total_nodes,
            returned_nodes=len(all_nodes),
            truncated=total_nodes > len(all_nodes),
            layout_hint="dagre" if view == "tree" else "force",
            algorithm_version=GRAPH_ALGORITHM_VERSION if view == "personalized" else None,
            weight_profile=GRAPH_WEIGHT_PROFILE if view == "personalized" else None,
        ),
    )


async def _load_graph(
    *,
    user_id: Optional[str],
    view: GraphView,
    focus_id: Optional[str],
    depth: int,
    max_nodes: int,
    include_mastered: bool,
    chapter_id: Optional[str] = None,
    keyword: Optional[str] = None,
    direction: str = "both",
) -> GraphData:
    """通用图谱聚合流程。"""
    if focus_id:
        try:
            exists = await asyncio.to_thread(_db_focus_exists, focus_id)
        except (DriverError, Neo4jError) as exc:
            raise GraphNeo4jError from exc
        except Exception as exc:
            raise GraphNeo4jError from exc
        if not exists:
            raise GraphFocusNotFoundError(focus_id)

    mastered_ids: set[str] = set()
    if user_id and not include_mastered:
        try:
            mastered_ids = await asyncio.to_thread(_db_query_mastered_ids, user_id)
        except Exception as exc:
            logger.error("图谱读取已掌握 ID 失败: %s", exc)
            raise GraphSqlServerError from exc

    try:
        selection = await asyncio.to_thread(
            _db_query_candidate_ids,
            focus_id,
            depth,
            chapter_id,
            keyword,
            direction,
            sorted(mastered_ids),
            max_nodes,
        )
    except (DriverError, Neo4jError) as exc:
        raise GraphNeo4jError from exc
    except Exception as exc:
        raise GraphNeo4jError from exc

    selected_ids = _select_render_ids(selection, focus_id, max_nodes)
    total_knowledge_points = int(
        getattr(selection, "total_count", len(selection))
    )
    total_chapters = getattr(selection, "chapter_count", None)

    try:
        rows = await asyncio.to_thread(_db_load_graph_rows, selected_ids)
    except (DriverError, Neo4jError) as exc:
        raise GraphNeo4jError from exc
    except Exception as exc:
        raise GraphNeo4jError from exc

    cycle_path = rows.get("cycle_path") or []
    if cycle_path:
        logger.error(
            "图谱查询范围存在环路: %s",
            " -> ".join(str(node_id) for node_id in cycle_path),
        )
        raise GraphNeo4jError("knowledge graph cycle detected")

    mastery_map: Dict[str, float] = {}
    if user_id:
        mastery_ids = list(
            dict.fromkeys(
                [
                    *selected_ids,
                    *[
                        row.get("id")
                        for row in rows.get("external_knowledge_points", [])
                        if row.get("id")
                    ],
                ]
            )
        )
        if mastery_ids:
            try:
                mastery_map = await asyncio.to_thread(
                    _db_query_mastery_map, user_id, mastery_ids
                )
            except Exception as exc:
                logger.error("图谱读取学生掌握度失败: %s", exc)
                raise GraphSqlServerError from exc

    if total_chapters is None:
        # 兼容 service 层单元测试传入普通 list；真实 Neo4j 查询会在
        # CandidateSelection 中直接携带 DB 侧统计，不会走这个回退。
        try:
            chapter_ids = await asyncio.to_thread(
                _db_query_chapter_ids, list(selection)
            )
        except (DriverError, Neo4jError) as exc:
            raise GraphNeo4jError from exc
        except Exception as exc:
            raise GraphNeo4jError from exc
        total_chapters = len(chapter_ids)

    logger.info(
        "图谱查询范围完成: focus_id=%s selected=%d total=%d chapters=%d",
        focus_id,
        len(selected_ids),
        total_knowledge_points,
        total_chapters,
    )
    try:
        return _build_graph_data(
            rows=rows,
            selected_ids=selected_ids,
            total_knowledge_points=total_knowledge_points,
            max_nodes=max_nodes,
            view=view,
            focus_id=focus_id,
            mastery_map=mastery_map,
            is_student=user_id is not None,
            total_chapters=total_chapters,
        )
    except KnowledgeGraphCycleError as exc:
        logger.error("图谱推荐检测到环路: %s", exc)
        raise GraphNeo4jError from exc


async def get_student_graph(
    user_id: str,
    view: GraphView = "personalized",
    focus_id: Optional[str] = None,
    depth: int = 2,
    max_nodes: int = 80,
    include_mastered: bool = True,
) -> GraphData:
    """读取学生图谱，合并当前学生掌握度及个性化推荐字段。"""
    return await _load_graph(
        user_id=user_id,
        view=view,
        focus_id=focus_id,
        depth=depth,
        max_nodes=max_nodes,
        include_mastered=include_mastered,
    )


async def get_student_neighbors(
    user_id: str,
    focus_id: str,
    direction: str = "both",
    depth: int = 1,
    max_nodes: int = 30,
) -> GraphData:
    """读取焦点节点局部邻居；方向和深度在一次 Neo4j 查询中完成。"""
    return await _load_graph(
        user_id=user_id,
        view="network",
        focus_id=focus_id,
        depth=depth,
        max_nodes=max_nodes,
        include_mastered=True,
        direction=direction,
    )


async def get_admin_graph(
    chapter_id: Optional[str] = None,
    keyword: Optional[str] = None,
    focus_id: Optional[str] = None,
    depth: int = 2,
    max_nodes: int = 200,
) -> GraphData:
    """读取管理端图谱，不访问学生掌握度数据。"""
    return await _load_graph(
        user_id=None,
        view="network",
        focus_id=focus_id,
        depth=depth,
        max_nodes=max_nodes,
        include_mastered=True,
        chapter_id=chapter_id,
        keyword=keyword,
    )
