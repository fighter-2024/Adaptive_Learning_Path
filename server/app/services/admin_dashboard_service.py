"""管理端仪表盘与学生数据看板业务服务。

SQL Server 负责用户、答题、诊断和掌握快照；Neo4j 负责知识点总量及名称。
本模块使用批量查询和单次连接内的多组 SQL，避免学生详情出现 N+1 查询。
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

import pyodbc

from app.db import get_driver
from app.db.sqlserver import get_connection, get_local_now
from app.models.admin_dashboard import (
    DashboardSummary,
    RecentDiagnosisItem,
    StudentAnswerHistoryItem,
    StudentDetail,
    StudentDetailMeta,
    StudentDiagnosisSummary,
    StudentLearningHistoryItem,
    StudentListItem,
)
from app.services.learning_path_service import recommend_path

logger = logging.getLogger(__name__)

RECENT_DIAGNOSIS_LIMIT = 8
ANSWER_HISTORY_LIMIT = 50
DIAGNOSIS_HISTORY_LIMIT = 10


def _format_datetime(value: object) -> Optional[str]:
    """把数据库时间转换成契约要求的 ISO 8601 秒精度字符串。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat()
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.replace(microsecond=0).isoformat()
    except ValueError:
        return text


def _average_mastery(alpha_vector: object) -> Optional[float]:
    """计算诊断 alpha 向量平均掌握度，空/非法向量返回 None。"""
    if not alpha_vector:
        return None
    try:
        values = [float(value) for value in json.loads(str(alpha_vector)).values()]
    except (TypeError, ValueError, json.JSONDecodeError, AttributeError):
        logger.warning("诊断 alpha_vector JSON 无法解析，按无平均掌握度处理")
        return None
    return sum(values) / len(values) if values else None


def _parse_alpha_vector(value: object) -> Dict[str, float]:
    """安全解析诊断 alpha 向量，不把脏历史数据暴露给前端。"""
    if not value:
        return {}
    try:
        raw = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        logger.warning("学生详情 alpha_vector JSON 无法解析，返回空向量")
        return {}
    if not isinstance(raw, dict):
        return {}
    result: Dict[str, float] = {}
    for key, probability in raw.items():
        try:
            result[str(key)] = max(0.0, min(1.0, float(probability)))
        except (TypeError, ValueError):
            continue
    return result


def _safe_rate(correct_count: int, questions_done: int) -> Optional[float]:
    """计算正确率；没有作答时返回契约约定的 null。"""
    return correct_count / questions_done if questions_done else None


def _db_count_knowledge_points() -> int:
    """从 Neo4j 读取知识点总数。"""
    driver = get_driver()
    with driver.session() as session:
        record = session.run(
            "MATCH (k:KnowledgePoint) RETURN count(k) AS total"
        ).single()
    return int(record["total"] or 0) if record else 0


def _db_load_knowledge_point_names(kp_ids: Sequence[str]) -> Dict[str, str]:
    """一次性读取知识点名称，避免详情页按知识点逐条查询。"""
    if not kp_ids:
        return {}
    driver = get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (k:KnowledgePoint)
            WHERE k.id IN $ids
            RETURN k.id AS id, k.name AS name
            """,
            ids=list(dict.fromkeys(kp_ids)),
        )
        return {
            str(record["id"]): str(record["name"] or record["id"])
            for record in result
            if record["id"] is not None
        }


def _db_dashboard_sql(week_start: datetime) -> dict:
    """一次 SQL Server 连接读取仪表盘的用户、题目和活跃学生统计。"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        student_count = cursor.execute(
            "SELECT COUNT(1) FROM users WHERE role = 'student' AND is_active = 1"
        ).fetchone()[0]
        question_count = cursor.execute(
            "SELECT COUNT(1) FROM questions WHERE is_active = 1"
        ).fetchone()[0]
        active_row = cursor.execute(
            """
            SELECT COUNT(DISTINCT activity.user_id)
            FROM (
                SELECT user_id FROM answer_records WHERE created_at >= ?
                UNION
                SELECT user_id FROM diagnosis_sessions WHERE diagnosed_at >= ?
            ) AS activity
            INNER JOIN users u ON u.user_id = activity.user_id
            WHERE u.role = 'student' AND u.is_active = 1
            """,
            (week_start, week_start),
        ).fetchone()
        recent_rows = cursor.execute(
            """
            SELECT TOP 8 d.user_id, u.name, d.diagnosed_at, d.alpha_vector
            FROM diagnosis_sessions d
            INNER JOIN users u ON u.user_id = d.user_id
            WHERE u.role = 'student' AND u.is_active = 1
            ORDER BY d.diagnosed_at DESC, d.id DESC
            """
        ).fetchall()
        return {
            "student_count": int(student_count or 0),
            "question_count": int(question_count or 0),
            "weekly_active_students": int(active_row[0] or 0) if active_row else 0,
            "recent_diagnoses": [
                {
                    "student_id": str(row[0]),
                    "student_name": str(row[1]),
                    "diagnosed_at": _format_datetime(row[2]) or "",
                    "average_mastery": _average_mastery(row[3]),
                }
                for row in recent_rows
            ],
        }
    finally:
        conn.close()


async def get_dashboard_summary() -> DashboardSummary:
    """读取仪表盘真实统计数据。"""
    now = get_local_now()
    week_start = datetime(now.year, now.month, now.day) - timedelta(days=now.weekday())
    sql_data, knowledge_point_count = await asyncio.gather(
        asyncio.to_thread(_db_dashboard_sql, week_start),
        asyncio.to_thread(_db_count_knowledge_points),
    )
    return DashboardSummary(
        knowledge_point_count=knowledge_point_count,
        **sql_data,
    )


def _student_filter(keyword: Optional[str]) -> Tuple[str, Tuple[str, ...]]:
    """生成学生列表复用的安全筛选 SQL 片段和参数。"""
    if not keyword:
        return "", ()
    value = f"%{keyword.strip()}%"
    return " AND (u.user_id LIKE ? OR u.username LIKE ? OR u.name LIKE ?)", (
        value,
        value,
        value,
    )


def _db_list_students(
    page: int, page_size: int, keyword: Optional[str], total_kp_count: int
) -> Tuple[List[StudentListItem], int]:
    """分页读取学生列表及其聚合统计。"""
    filter_sql, filter_params = _student_filter(keyword)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        total = cursor.execute(
            "SELECT COUNT(1) FROM users u "
            "WHERE u.role = 'student' AND u.is_active = 1" + filter_sql,
            filter_params,
        ).fetchone()[0]
        offset = (page - 1) * page_size
        rows = cursor.execute(
            """
            SELECT u.user_id, u.username, u.name, u.created_at,
                   COALESCE(a.total_questions_done, 0),
                   COALESCE(m.mastered_kp_count, 0),
                   m.average_mastery,
                   CASE
                       WHEN a.last_answer_at IS NULL THEN d.last_diagnosed_at
                       WHEN d.last_diagnosed_at IS NULL THEN a.last_answer_at
                       WHEN a.last_answer_at >= d.last_diagnosed_at THEN a.last_answer_at
                       ELSE d.last_diagnosed_at
                   END AS last_active
            FROM users u
            LEFT JOIN (
                SELECT user_id, COUNT(1) AS total_questions_done,
                       MAX(created_at) AS last_answer_at
                FROM answer_records
                GROUP BY user_id
            ) a ON a.user_id = u.user_id
            LEFT JOIN (
                SELECT user_id,
                       SUM(CASE WHEN mastery_probability >= 0.8 THEN 1 ELSE 0 END)
                           AS mastered_kp_count,
                       AVG(mastery_probability) AS average_mastery
                FROM user_kp_mastery
                GROUP BY user_id
            ) m ON m.user_id = u.user_id
            LEFT JOIN (
                SELECT user_id, MAX(diagnosed_at) AS last_diagnosed_at
                FROM diagnosis_sessions
                GROUP BY user_id
            ) d ON d.user_id = u.user_id
            WHERE u.role = 'student' AND u.is_active = 1
            """
            + filter_sql
            + " ORDER BY last_active DESC, u.user_id "
            + "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
            (*filter_params, offset, page_size),
        ).fetchall()
        items = [
            StudentListItem(
                student_id=str(row[0]),
                username=str(row[1]),
                name=str(row[2]),
                total_questions_done=int(row[4] or 0),
                mastered_kp_count=int(row[5] or 0),
                total_kp_count=total_kp_count,
                average_mastery=float(row[6]) if row[6] is not None else None,
                last_active=_format_datetime(row[7]),
                created_at=_format_datetime(row[3]),
            )
            for row in rows
        ]
        return items, int(total or 0)
    finally:
        conn.close()


async def list_students(
    page: int = 1, page_size: int = 20, keyword: Optional[str] = None
) -> Tuple[List[StudentListItem], int]:
    """分页、搜索读取学生列表。"""
    total_kp_count = await asyncio.to_thread(_db_count_knowledge_points)
    return await asyncio.to_thread(
        _db_list_students, page, page_size, keyword, total_kp_count
    )


def _db_load_student_rows(student_id: str) -> Optional[dict]:
    """在一个 SQL Server 连接内读取学生详情的基础、掌握、诊断和答题数据。"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        user_row = cursor.execute(
            """
            SELECT user_id, username, name, avatar, created_at, last_login_at
            FROM users
            WHERE user_id = ? AND role = 'student' AND is_active = 1
            """,
            (student_id,),
        ).fetchone()
        if user_row is None:
            return None

        mastery_rows = cursor.execute(
            """
            SELECT knowledge_point_id, mastery_probability, questions_done,
                   correct_count, updated_at
            FROM user_kp_mastery
            WHERE user_id = ?
            ORDER BY mastery_probability ASC, updated_at DESC, knowledge_point_id
            """,
            (student_id,),
        ).fetchall()
        diagnosis_rows = cursor.execute(
            """
            SELECT TOP 10 session_id, alpha_vector, question_count, diagnosed_at,
                   algorithm_version, parameter_version, answer_time_from,
                   answer_time_to, repeat_strategy, converged, iterations
            FROM diagnosis_sessions
            WHERE user_id = ?
            ORDER BY diagnosed_at DESC, id DESC
            """,
            (student_id,),
        ).fetchall()
        answer_rows = cursor.execute(
            """
            SELECT TOP 50 ar.record_id, ar.question_id, q.content,
                   ar.student_answer, ar.is_correct, ar.time_spent, ar.created_at
            FROM answer_records ar
            LEFT JOIN questions q ON q.question_id = ar.question_id
            WHERE ar.user_id = ?
            ORDER BY ar.created_at DESC, ar.id DESC
            """,
            (student_id,),
        ).fetchall()
        return {
            "user": user_row,
            "mastery": mastery_rows,
            "diagnoses": diagnosis_rows,
            "answers": answer_rows,
        }
    finally:
        conn.close()


def _diagnosis_summary(row: Sequence[object]) -> StudentDiagnosisSummary:
    """把诊断表行转换成前端可读摘要。"""
    return StudentDiagnosisSummary(
        session_id=str(row[0]) if row[0] is not None else None,
        diagnosed_at=_format_datetime(row[3]) or "",
        question_count=int(row[2] or 0),
        average_mastery=_average_mastery(row[1]),
        algorithm_version=str(row[4]) if row[4] is not None else None,
        parameter_version=str(row[5]) if row[5] is not None else None,
        answer_time_from=_format_datetime(row[6]),
        answer_time_to=_format_datetime(row[7]),
        repeat_strategy=str(row[8]) if row[8] is not None else None,
        converged=bool(row[9]) if row[9] is not None else None,
        iterations=int(row[10]) if row[10] is not None else None,
    )


async def get_student_detail(student_id: str) -> Optional[StudentDetail]:
    """读取目标学生详情并生成当前推荐路径。"""
    raw = await asyncio.to_thread(_db_load_student_rows, student_id)
    if raw is None:
        return None

    user_row = raw["user"]
    mastery_rows = raw["mastery"]
    diagnosis_rows = raw["diagnoses"]
    answer_rows = raw["answers"]

    kp_ids = [str(row[0]) for row in mastery_rows]
    alpha_vector = _parse_alpha_vector(diagnosis_rows[0][1]) if diagnosis_rows else {}
    kp_ids.extend(alpha_vector.keys())
    names = await asyncio.to_thread(_db_load_knowledge_point_names, kp_ids)

    learning_by_id = {
        str(row[0]): StudentLearningHistoryItem(
            knowledge_point_id=str(row[0]),
            knowledge_point_name=names.get(str(row[0]), str(row[0])),
            questions_done=int(row[2] or 0),
            correct_count=int(row[3] or 0),
            correct_rate=_safe_rate(int(row[3] or 0), int(row[2] or 0)),
            mastery_probability=float(row[1]) if row[1] is not None else None,
            updated_at=_format_datetime(row[4]),
        )
        for row in mastery_rows
    }
    # 诊断 alpha 通常包含 Q 矩阵中的全部知识点；没有答题快照的节点也要
    # 出现在看板中，显示为 0 次作答，避免管理员误以为其数据串到了别的学生。
    for kp_id, probability in alpha_vector.items():
        learning_by_id.setdefault(
            kp_id,
            StudentLearningHistoryItem(
                knowledge_point_id=kp_id,
                knowledge_point_name=names.get(kp_id, kp_id),
                questions_done=0,
                correct_count=0,
                correct_rate=None,
                mastery_probability=probability,
                updated_at=None,
            ),
        )
    learning_history = sorted(
        learning_by_id.values(),
        key=lambda item: (
            item.mastery_probability is None,
            item.mastery_probability if item.mastery_probability is not None else 0.0,
            item.knowledge_point_id,
        ),
    )
    diagnosis_history = [_diagnosis_summary(row) for row in diagnosis_rows]
    answer_history = [
        StudentAnswerHistoryItem(
            record_id=str(row[0]),
            question_id=str(row[1]),
            question_content=str(row[2]) if row[2] is not None else None,
            student_answer=str(row[3]),
            is_correct=bool(row[4]),
            time_spent=int(row[5]) if row[5] is not None else None,
            created_at=_format_datetime(row[6]) or "",
        )
        for row in answer_rows
    ]

    # 推荐路径复用已通过 M7 的拓扑约束算法；student_id 只来自当前详情 URL
    # 对应的管理员查询结果，不会从客户端传入任意学生身份。
    path_data = await recommend_path(student_id, None, count=8)
    recommended_path = path_data.steps

    return StudentDetail(
        student_id=str(user_row[0]),
        username=str(user_row[1]),
        name=str(user_row[2]),
        avatar=str(user_row[3]) if user_row[3] is not None else None,
        created_at=_format_datetime(user_row[4]),
        last_login_at=_format_datetime(user_row[5]),
        alpha_vector=alpha_vector,
        last_diagnosis=diagnosis_history[0] if diagnosis_history else None,
        diagnosis_history=diagnosis_history,
        learning_history=learning_history,
        answer_history=answer_history,
        recommended_path=recommended_path,
        meta=StudentDetailMeta(
            answer_history_limit=ANSWER_HISTORY_LIMIT,
            diagnosis_history_limit=DIAGNOSIS_HISTORY_LIMIT,
            learning_history_total=len(learning_history),
            knowledge_point_source="Neo4j KnowledgePoint + SQL Server user_kp_mastery",
        ),
    )
