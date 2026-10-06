"""学员正式取题服务。

知识点存在性由 Neo4j 负责，题目、Q 矩阵和答题记录由 SQL Server 负责。
该服务只构造学生安全视图，绝不把 answer/explanation 传到响应模型。
"""

from __future__ import annotations

import asyncio
from typing import List, Optional, Tuple

from app.db import get_driver
from app.db.sqlserver import get_connection
from app.models.student_question import (
    StudentQuestionItem,
    StudentQuestionList,
    StudentQuestionType,
)
from app.services.question_service import json_to_options


class StudentQuestionKnowledgePointNotFoundError(Exception):
    """请求的知识点不存在于 Neo4j。"""

    def __init__(self, knowledge_point_id: str) -> None:
        self.knowledge_point_id = knowledge_point_id
        super().__init__(f"知识点 {knowledge_point_id} 不存在")


def _db_knowledge_point_exists(knowledge_point_id: str) -> bool:
    """只读查询 Neo4j 中的知识点是否存在。"""
    driver = get_driver()
    with driver.session() as session:
        record = session.run(
            "MATCH (k:KnowledgePoint {id: $id}) RETURN k.id AS id LIMIT 1",
            id=knowledge_point_id,
        ).single()
    return record is not None and record["id"] is not None


def _db_list_student_questions(
    knowledge_point_id: str,
    user_id: str,
    count: int,
    exclude_done: bool,
    question_type: Optional[StudentQuestionType],
) -> Tuple[List[dict], int]:
    """查询题目并只返回学生可见字段。"""
    clauses = [
        "q.is_active = 1",
        "EXISTS (SELECT 1 FROM q_matrix m "
        "WHERE m.question_id = q.question_id AND m.knowledge_point_id = ?)",
    ]
    params: List[object] = [knowledge_point_id]
    if question_type:
        clauses.append("q.type = ?")
        params.append(question_type)
    if exclude_done:
        clauses.append(
            "NOT EXISTS (SELECT 1 FROM answer_records ar "
            "WHERE ar.user_id = ? AND ar.question_id = q.question_id)"
        )
        params.append(user_id)

    where_sql = " AND ".join(clauses)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        total = int(
            cursor.execute(
                f"SELECT COUNT(1) FROM questions q WHERE {where_sql}",
                tuple(params),
            ).fetchone()[0]
        )
        if total == 0:
            return [], 0

        rows = cursor.execute(
            f"SELECT q.question_id, q.content, q.type, q.difficulty, q.options "
            f"FROM questions q WHERE {where_sql} ORDER BY q.id "
            "OFFSET 0 ROWS FETCH NEXT ? ROWS ONLY",
            tuple(params + [count]),
        ).fetchall()
        items = [
            {
                "id": row[0],
                "content": row[1],
                "type": row[2],
                "difficulty": row[3],
                "options": json_to_options(row[4]),
            }
            for row in rows
        ]
        return items, total
    finally:
        conn.close()


async def list_student_questions(
    knowledge_point_id: str,
    user_id: str,
    count: int,
    exclude_done: bool,
    question_type: Optional[StudentQuestionType],
) -> StudentQuestionList:
    """验证知识点并查询学生安全题目列表。"""
    exists = await asyncio.to_thread(
        _db_knowledge_point_exists, knowledge_point_id
    )
    if not exists:
        raise StudentQuestionKnowledgePointNotFoundError(knowledge_point_id)

    rows, total = await asyncio.to_thread(
        _db_list_student_questions,
        knowledge_point_id,
        user_id,
        count,
        exclude_done,
        question_type,
    )
    return StudentQuestionList(
        list=[StudentQuestionItem(**row) for row in rows],
        total=total,
    )
