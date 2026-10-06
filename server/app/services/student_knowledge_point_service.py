"""
学员端知识点业务服务

为学员端「学习」模块提供知识点视角的数据聚合，数据来源严格按
AI开发总则第六条「数据库职责划分」：
- 知识点节点属性 + 前置依赖拓扑    → Neo4j（图谱职责）
- 学员掌握概率快照 user_kp_mastery → SQL Server（DINA 诊断结果）
- 题目与题目-知识点关联 q_matrix   → SQL Server
- 答题记录 answer_records          → SQL Server（判定题目是否已做）

掌握状态枚举（严格对照 docs/API契约文档.md「2.1 学习」）：
    mastered   ≥ 0.8
    learning   0.4 ≤ p < 0.8
    weak       < 0.4
    not_started 无掌握数据（user_kp_mastery 无该用户记录，或未登录）

Service 层不接触 HTTP 对象，只处理业务数据；所有同步 Neo4j / SQL Server
操作通过 asyncio.to_thread 放入线程池执行，避免阻塞事件循环。

降级策略（与既有 question_count 降级惯例一致）：
- SQL Server 侧查询失败 → 掌握概率为 None（status=not_started）、done 为
  false、questions 为空列表，记录 warning 不阻塞接口；
- Neo4j 异常向上抛，由 router 统一映射为 50002。
"""

import asyncio
import logging
from typing import Dict, List, Optional, Set

from app.db import get_driver
from app.models.student_knowledge_point import (
    StudentKnowledgePointDetail,
    StudentKnowledgePointItem,
    StudentPrerequisiteItem,
    StudentKnowledgePointQuestionItem,
)

logger = logging.getLogger(__name__)

# 掌握状态阈值（对照 API 契约：mastered ≥ 0.8，weak < 0.4，其余 learning）
MASTERED_THRESHOLD = 0.8
LEARNING_THRESHOLD = 0.4


# ==================== 纯函数工具（便于单元测试） ====================


def compute_mastery_status(mastery_probability: Optional[float]) -> str:
    """根据掌握概率计算掌握状态

    阈值边界（对照契约）：
    - mastered:   ≥ 0.8
    - learning:   0.4 ≤ p < 0.8
    - weak:       < 0.4
    - not_started: 无数据（None）

    Args:
        mastery_probability: 掌握概率 0.0~1.0；None 表示无诊断数据

    Returns:
        mastered / learning / weak / not_started
    """
    if mastery_probability is None:
        return "not_started"
    if mastery_probability >= MASTERED_THRESHOLD:
        return "mastered"
    if mastery_probability >= LEARNING_THRESHOLD:
        return "learning"
    return "weak"


def is_mastered(mastery_probability: Optional[float]) -> bool:
    """判断某知识点是否已掌握（掌握概率 ≥ 0.8）

    用于详情接口中前置知识点的 mastered 字段。

    Args:
        mastery_probability: 掌握概率；None 表示无数据

    Returns:
        True 表示已掌握
    """
    return mastery_probability is not None and mastery_probability >= MASTERED_THRESHOLD


# ==================== Neo4j 同步操作（线程池执行） ====================


def _db_list_student_kps() -> List[dict]:
    """查询全部知识点基础信息（同步执行）

    仅取学员列表需要的字段；chapter_name 通过 BELONGS_TO 可选关联，
    章节节点不存在时为 None。排序与管理端列表保持一致：
    chapter.sort_order → k.sort_order → k.id。

    Returns:
        知识点字典列表：{id, name, chapter_name, difficulty, estimated_time}
    """
    driver = get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (k:KnowledgePoint)
            OPTIONAL MATCH (c:Chapter {id: k.chapter_id})
            RETURN k.id AS id,
                   k.name AS name,
                   c.name AS chapter_name,
                   k.difficulty AS difficulty,
                   k.estimated_time AS estimated_time
            ORDER BY c.sort_order, k.sort_order, k.id
            """
        )
        rows: List[dict] = []
        for record in result:
            rows.append(
                {
                    "id": record["id"],
                    "name": record["name"],
                    "chapter_name": record["chapter_name"],
                    # 历史导入数据可能缺属性，给默认值保证模型校验通过
                    "difficulty": record["difficulty"]
                    if record["difficulty"] is not None
                    else 0.0,
                    "estimated_time": record["estimated_time"]
                    if record["estimated_time"] is not None
                    else 0,
                }
            )
    return rows


def _db_get_student_kp_detail(kp_id: str) -> Optional[dict]:
    """查询知识点详情及前置知识点列表（同步执行）

    前置知识点取入边（前置)-[:PREREQUISITE]->(当前)，与管理端
    _db_get_detail 的语义一致。

    Args:
        kp_id: 知识点 ID

    Returns:
        {id, name, description, difficulty, estimated_time,
         prerequisites: [{id, name}, ...]}；知识点不存在时返回 None
    """
    driver = get_driver()
    with driver.session() as session:
        record = session.run(
            """
            MATCH (k:KnowledgePoint {id: $id})
            OPTIONAL MATCH (pre:KnowledgePoint)-[:PREREQUISITE]->(k)
            RETURN k.id AS id,
                   k.name AS name,
                   k.description AS description,
                   k.difficulty AS difficulty,
                   k.estimated_time AS estimated_time,
                   [pre IN collect(DISTINCT pre) WHERE pre IS NOT NULL
                    | {id: pre.id, name: pre.name}] AS prerequisites
            """,
            id=kp_id,
        ).single()

    if record is None or record["id"] is None:
        return None

    return {
        "id": record["id"],
        "name": record["name"],
        "description": record.get("description") or "",
        "difficulty": record.get("difficulty")
        if record.get("difficulty") is not None
        else 0.0,
        "estimated_time": record.get("estimated_time")
        if record.get("estimated_time") is not None
        else 0,
        "prerequisites": sorted(record["prerequisites"], key=lambda x: x["id"]),
    }


# ==================== SQL Server 同步操作（线程池执行） ====================


def _db_query_mastery_map(user_id: str, kp_ids: List[str]) -> Dict[str, float]:
    """从 user_kp_mastery 批量查询学员掌握概率（同步执行）

    掌握快照表职责见 docs/数据库设计.md「1.7 user_kp_mastery」：
    每次答题后实时更新，无历史，无记录即无数据（not_started）。

    Args:
        user_id: 学生业务 ID
        kp_ids: 知识点 ID 列表

    Returns:
        {knowledge_point_id: mastery_probability}，无记录的 ID 不在结果中
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
            f"SELECT knowledge_point_id, mastery_probability FROM user_kp_mastery "
            f"WHERE user_id = ? AND knowledge_point_id IN ({placeholders})",
            (user_id, *kp_ids),
        )
        return {row[0]: float(row[1]) for row in cursor.fetchall()}
    finally:
        conn.close()


def _db_query_kp_questions(kp_id: str) -> List[dict]:
    """查询知识点关联的启用中题目（同步执行）

    题目-知识点关联走 q_matrix 表（SQL Server 职责）。
    学员视角仅返回摘要字段（不含 options/answer/explanation，避免泄题）。

    Args:
        kp_id: 知识点 ID

    Returns:
        题目字典列表（按题目表自增 id 排序）：
        {id, content, type, difficulty}
    """
    from app.db.sqlserver import get_connection

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT q.question_id, q.content, q.type, q.difficulty "
            "FROM questions q "
            "INNER JOIN q_matrix m ON m.question_id = q.question_id "
            "WHERE m.knowledge_point_id = ? AND q.is_active = 1 "
            "ORDER BY q.id",
            (kp_id,),
        )
        return [
            {
                "id": row[0],
                "content": row[1],
                "type": row[2],
                "difficulty": row[3],
            }
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()


def _db_query_done_question_ids(user_id: str, question_ids: List[str]) -> Set[str]:
    """查询学员已做过的题目 ID 集合（同步执行）

    依据 answer_records 表（docs/数据库设计.md「1.5」）：
    只要该学员对这道题有过作答记录即视为已做（done=true），
    不区分答对答错。

    Args:
        user_id: 学生业务 ID
        question_ids: 待判定的题目 ID 列表

    Returns:
        该学员在 answer_records 中出现过的题目 ID 集合
    """
    if not question_ids:
        return set()
    from app.db.sqlserver import get_connection

    placeholders = ", ".join(["?"] * len(question_ids))
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT DISTINCT question_id FROM answer_records "
            f"WHERE user_id = ? AND question_id IN ({placeholders})",
            (user_id, *question_ids),
        )
        return {row[0] for row in cursor.fetchall()}
    finally:
        conn.close()


# ==================== 异步服务接口 ====================


async def list_student_knowledge_points(
    user_id: Optional[str],
) -> List[StudentKnowledgePointItem]:
    """查询学员视角知识点列表（含每个知识点的掌握概率与掌握状态）

    Args:
        user_id: 学生业务 ID；None 表示未登录（匿名视角，全部 not_started）

    Returns:
        学员视角知识点列表（契约结构 {list: [...]}，非分页）

    Note:
        SQL Server 不可用时掌握数据降级为 None（status=not_started）并
        记录 warning，不阻塞列表查询；Neo4j 异常向上抛。
    """
    rows = await asyncio.to_thread(_db_list_student_kps)

    # 批量查询掌握概率（SQL Server），失败降级为无数据
    mastery_map: Dict[str, float] = {}
    if user_id:
        try:
            mastery_map = await asyncio.to_thread(
                _db_query_mastery_map, user_id, [row["id"] for row in rows]
            )
        except Exception as e:
            logger.warning(
                "查询学员掌握概率失败（SQL Server），降级为 not_started: %s", e
            )

    items: List[StudentKnowledgePointItem] = []
    for row in rows:
        probability = mastery_map.get(row["id"])
        items.append(
            StudentKnowledgePointItem(
                id=row["id"],
                name=row["name"],
                chapter_name=row["chapter_name"],
                difficulty=row["difficulty"],
                estimated_time=row["estimated_time"],
                mastery_probability=probability,
                status=compute_mastery_status(probability),
            )
        )
    return items


async def get_student_knowledge_point(
    kp_id: str, user_id: Optional[str]
) -> Optional[StudentKnowledgePointDetail]:
    """查询学员视角知识点详情（前置掌握状态 + 关联题目列表）

    Args:
        kp_id: 知识点 ID
        user_id: 学生业务 ID；None 表示未登录（匿名视角，
            前置均未掌握、题目均未做）

    Returns:
        StudentKnowledgePointDetail 或 None（知识点不存在）

    Note:
        SQL Server 侧失败时降级：掌握概率为 None、done 为 false、
        questions 为空列表；Neo4j 异常向上抛。
    """
    data = await asyncio.to_thread(_db_get_student_kp_detail, kp_id)
    if data is None:
        return None

    # 本知识点 + 全部前置知识点的掌握概率（SQL Server，失败降级）
    prereq_ids = [item["id"] for item in data["prerequisites"]]
    mastery_map: Dict[str, float] = {}
    if user_id:
        try:
            mastery_map = await asyncio.to_thread(
                _db_query_mastery_map, user_id, [kp_id] + prereq_ids
            )
        except Exception as e:
            logger.warning(
                "查询学员掌握概率失败（SQL Server），降级为无数据: %s", e
            )

    # 关联题目列表（SQL Server，失败降级为空）
    questions: List[dict] = []
    try:
        questions = await asyncio.to_thread(_db_query_kp_questions, kp_id)
    except Exception as e:
        logger.warning(
            "查询知识点关联题目失败（SQL Server），questions 降级为空: %s", e
        )

    # 已做题目集合（SQL Server，失败降级为全部未做）
    done_ids: Set[str] = set()
    if user_id and questions:
        try:
            done_ids = await asyncio.to_thread(
                _db_query_done_question_ids,
                user_id,
                [question["id"] for question in questions],
            )
        except Exception as e:
            logger.warning(
                "查询学员已做题目失败（SQL Server），done 降级为 false: %s", e
            )

    return StudentKnowledgePointDetail(
        id=data["id"],
        name=data["name"],
        description=data["description"],
        difficulty=data["difficulty"],
        estimated_time=data["estimated_time"],
        mastery_probability=mastery_map.get(kp_id),
        prerequisites=[
            StudentPrerequisiteItem(
                id=item["id"],
                name=item["name"],
                mastered=is_mastered(mastery_map.get(item["id"])),
            )
            for item in data["prerequisites"]
        ],
        questions=[
            StudentKnowledgePointQuestionItem(
                id=question["id"],
                content=question["content"],
                type=question["type"],
                difficulty=question["difficulty"],
                done=question["id"] in done_ids,
            )
            for question in questions
        ],
    )
