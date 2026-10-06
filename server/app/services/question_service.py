"""
题库管理业务服务

负责题目在 SQL Server 中的增删改查（questions 表 + q_matrix 表）：
- 题干/选项/答案/解析存 questions 表，选项序列化为 JSON 存 NVARCHAR(MAX) 列
- 题目-知识点关联存 q_matrix 表（DINA 的 Q矩阵）
知识点存在性校验与名称查询走 Neo4j（AI开发总则第六条：图谱拓扑归图数据库）。
Service 层不接触 HTTP 对象，只处理业务数据；同步数据库操作经
asyncio.to_thread 放入线程池执行，避免阻塞事件循环。
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from pydantic import ValidationError

from app.db import get_driver
from app.db.sqlserver import get_connection
from app.models.question import (
    QuestionBatchImportResult,
    QuestionCreateRequest,
    QuestionDetail,
    QuestionImportError,
    QuestionListItem,
    QuestionOption,
)

logger = logging.getLogger(__name__)

# ==================== 业务异常 ====================
# Router 层捕获这些异常并映射为统一响应码，不向客户端暴露内部堆栈。


class QuestionNotFoundError(Exception):
    """题目不存在"""

    def __init__(self, question_id: str) -> None:
        self.question_id = question_id
        super().__init__(f"题目 {question_id} 不存在")


class KnowledgePointMissingError(Exception):
    """关联知识点不存在（Neo4j 中查不到对应节点）"""

    def __init__(self, missing_ids: List[str]) -> None:
        self.missing_ids = missing_ids
        super().__init__("关联知识点不存在: " + ", ".join(missing_ids))


# ==================== 纯函数工具（便于单元测试） ====================


def _generate_question_id() -> str:
    """生成题目业务 ID

    Returns:
        形如 q_xxxxxxxx 的 ID（8 位十六进制，与 kp_/stu_ 风格一致）
    """
    return f"q_{uuid.uuid4().hex[:8]}"


def options_to_json(options: List[dict]) -> str:
    """选项列表序列化为 JSON 字符串（存 questions.options 列）

    Args:
        options: 选项字典列表，形如 [{"label": "A", "content": "..."}]

    Returns:
        JSON 字符串（ensure_ascii=False 保留中文原文）
    """
    return json.dumps(options, ensure_ascii=False)


def json_to_options(raw: Optional[str]) -> List[dict]:
    """JSON 字符串解析为选项列表

    空值或非法 JSON 返回空列表并记录 warning（历史脏数据不阻塞接口）。

    Args:
        raw: questions.options 列原始值

    Returns:
        选项字典列表；解析失败时为空列表
    """
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("questions.options JSON 解析失败: %s", e)
        return []
    return data if isinstance(data, list) else []


def _format_datetime(value) -> Optional[str]:
    """将数据库 DATETIME 值格式化为 ISO 8601 字符串（契约时间格式）

    Args:
        value: datetime 对象、字符串或 None

    Returns:
        形如 2026-01-15T10:00:00 的字符串；None 原样返回
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, str):
        return value.replace(" ", "T")[:19]
    return str(value)


def first_validation_message(exc: ValidationError) -> str:
    """提取 Pydantic 校验异常的第一条用户可读信息

    用于批量导入逐行报错：去掉 "Value error, " 前缀，
    保留业务校验时抛出的中文提示（如「选项不能为空」）。

    Args:
        exc: Pydantic ValidationError

    Returns:
        第一条校验错误信息
    """
    errors = exc.errors()
    if not errors:
        return "数据校验失败"
    message = errors[0].get("msg", "数据校验失败")
    prefix = "Value error, "
    if message.startswith(prefix):
        message = message[len(prefix):]
    return message


# ==================== SQL Server 同步操作（线程池执行） ====================


def _db_list_page(
    page: int,
    page_size: int,
    knowledge_point_id: Optional[str],
    question_type: Optional[str],
    difficulty_min: Optional[float],
    difficulty_max: Optional[float],
    keyword: Optional[str],
) -> Tuple[int, List[dict]]:
    """分页查询题目（同步执行）

    动态拼 WHERE 条件（全部参数化，无 SQL 注入风险）：
    - knowledge_point_id: q_matrix 存在该知识点关联
    - question_type: 题型精确匹配
    - difficulty_min / difficulty_max: 难度区间筛选（闭区间，含边界，可单独使用）
    - keyword: 题干模糊搜索（LIKE）
    """
    where_clauses = ["q.is_active = 1"]
    params: List[object] = []
    if knowledge_point_id:
        where_clauses.append(
            "EXISTS (SELECT 1 FROM q_matrix m "
            "WHERE m.question_id = q.question_id AND m.knowledge_point_id = ?)"
        )
        params.append(knowledge_point_id)
    if question_type:
        where_clauses.append("q.type = ?")
        params.append(question_type)
    if difficulty_min is not None:
        where_clauses.append("q.difficulty >= ?")
        params.append(difficulty_min)
    if difficulty_max is not None:
        where_clauses.append("q.difficulty <= ?")
        params.append(difficulty_max)
    if keyword:
        where_clauses.append("q.content LIKE ?")
        params.append(f"%{keyword}%")
    where_sql = " AND ".join(where_clauses)
    skip = (page - 1) * page_size

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT COUNT(1) FROM questions q WHERE {where_sql}", tuple(params)
        )
        total = int(cursor.fetchone()[0])
        cursor.execute(
            f"SELECT q.question_id, q.content, q.type, q.difficulty, q.created_at "
            f"FROM questions q WHERE {where_sql} "
            f"ORDER BY q.id DESC OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
            tuple(params + [skip, page_size]),
        )
        rows = [
            {
                "id": row[0],
                "content": row[1],
                "type": row[2],
                "difficulty": row[3],
                "created_at": _format_datetime(row[4]),
            }
            for row in cursor.fetchall()
        ]
        return total, rows
    finally:
        conn.close()


def _db_get_question_kp_ids(question_ids: List[str]) -> Dict[str, List[str]]:
    """从 q_matrix 批量查询题目关联的知识点 ID（同步执行）

    Args:
        question_ids: 题目 ID 列表

    Returns:
        {question_id: [knowledge_point_id, ...]}（按插入顺序）
    """
    if not question_ids:
        return {}
    placeholders = ", ".join(["?"] * len(question_ids))
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT question_id, knowledge_point_id FROM q_matrix "
            f"WHERE question_id IN ({placeholders}) ORDER BY id",
            tuple(question_ids),
        )
        result: Dict[str, List[str]] = {}
        for question_id, kp_id in cursor.fetchall():
            result.setdefault(question_id, []).append(kp_id)
        return result
    finally:
        conn.close()


def _db_get_question(question_id: str) -> Optional[dict]:
    """查询单个题目详情 + 关联知识点（同步执行）

    Args:
        question_id: 题目 ID

    Returns:
        题目详情字典（options 已解析为列表）；题目不存在时返回 None
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT question_id, content, type, difficulty, options, answer, "
            "explanation, created_at FROM questions "
            "WHERE question_id = ? AND is_active = 1",
            (question_id,),
        ).fetchone()
        if row is None:
            return None
        kp_rows = cursor.execute(
            "SELECT knowledge_point_id FROM q_matrix WHERE question_id = ? ORDER BY id",
            (question_id,),
        ).fetchall()
        kp_ids = [r[0] for r in kp_rows]
    finally:
        conn.close()

    return {
        "id": row[0],
        "content": row[1],
        "type": row[2],
        "difficulty": row[3],
        "options": json_to_options(row[4]),
        "answer": row[5],
        "explanation": row[6] or "",
        "knowledge_point_ids": kp_ids,
        "created_at": _format_datetime(row[7]),
    }


def _db_create_question(
    question_id: str,
    content: str,
    question_type: str,
    difficulty: float,
    options_json: str,
    answer: str,
    explanation: str,
    kp_ids: List[str],
) -> dict:
    """新增题目 + Q矩阵关联（同一事务，同步执行）

    题目插入 questions 表，Q矩阵行插入 q_matrix 表；
    任一步失败整体回滚（get_connection 返回的连接 autocommit=False）。

    Returns:
        创建后的题目详情字典（含 created_at）
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO questions (question_id, content, type, difficulty, "
            "options, answer, explanation) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (question_id, content, question_type, difficulty, options_json, answer, explanation),
        )
        if kp_ids:
            cursor.executemany(
                "INSERT INTO q_matrix (question_id, knowledge_point_id) VALUES (?, ?)",
                [(question_id, kp_id) for kp_id in kp_ids],
            )
        row = cursor.execute(
            "SELECT created_at FROM questions WHERE question_id = ?", (question_id,)
        ).fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "id": question_id,
        "content": content,
        "type": question_type,
        "difficulty": difficulty,
        "options": json_to_options(options_json),
        "answer": answer,
        "explanation": explanation,
        "knowledge_point_ids": kp_ids,
        "created_at": _format_datetime(row[0]) if row else None,
    }


def _db_update_question(
    question_id: str,
    content: str,
    question_type: str,
    difficulty: float,
    options_json: str,
    answer: str,
    explanation: str,
    kp_ids: List[str],
) -> Optional[dict]:
    """编辑题目并同步更新 Q矩阵（同一事务，同步执行）

    Q矩阵更新策略：先删除该题目全部旧关联，再按新列表插入（全量替换）。

    Returns:
        更新后的题目详情字典；题目不存在时返回 None
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        exists = cursor.execute(
            "SELECT question_id FROM questions WHERE question_id = ? AND is_active = 1",
            (question_id,),
        ).fetchone()
        if exists is None:
            conn.rollback()
            return None

        cursor.execute(
            "UPDATE questions SET content = ?, type = ?, difficulty = ?, "
            "options = ?, answer = ?, explanation = ?, updated_at = GETDATE() "
            "WHERE question_id = ?",
            (content, question_type, difficulty, options_json, answer, explanation, question_id),
        )
        # 同步 Q矩阵：全量替换（先删后插）
        cursor.execute("DELETE FROM q_matrix WHERE question_id = ?", (question_id,))
        if kp_ids:
            cursor.executemany(
                "INSERT INTO q_matrix (question_id, knowledge_point_id) VALUES (?, ?)",
                [(question_id, kp_id) for kp_id in kp_ids],
            )
        row = cursor.execute(
            "SELECT created_at FROM questions WHERE question_id = ?", (question_id,)
        ).fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "id": question_id,
        "content": content,
        "type": question_type,
        "difficulty": difficulty,
        "options": json_to_options(options_json),
        "answer": answer,
        "explanation": explanation,
        "knowledge_point_ids": kp_ids,
        "created_at": _format_datetime(row[0]) if row else None,
    }


def _db_delete_question(question_id: str) -> None:
    """删除题目并同步删除 Q矩阵关联（同一事务，同步执行）

    Raises:
        QuestionNotFoundError: 题目不存在
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        exists = cursor.execute(
            "SELECT question_id FROM questions WHERE question_id = ? AND is_active = 1",
            (question_id,),
        ).fetchone()
        if exists is None:
            conn.rollback()
            raise QuestionNotFoundError(question_id)
        cursor.execute("DELETE FROM q_matrix WHERE question_id = ?", (question_id,))
        cursor.execute("DELETE FROM questions WHERE question_id = ?", (question_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ==================== Neo4j 同步操作（线程池执行） ====================


def _db_check_kp_exist(kp_ids: List[str]) -> Set[str]:
    """查询 Neo4j 中存在的知识点 ID 集合（同步执行）

    知识点节点是图数据库职责（AI开发总则第六条），q_matrix 的
    knowledge_point_id 对应 Neo4j KnowledgePoint.id。

    Args:
        kp_ids: 待校验的知识点 ID 列表

    Returns:
        Neo4j 中实际存在的知识点 ID 集合
    """
    if not kp_ids:
        return set()
    driver = get_driver()
    with driver.session() as session:
        record = session.run(
            "MATCH (k:KnowledgePoint) WHERE k.id IN $ids RETURN collect(k.id) AS ids",
            ids=kp_ids,
        ).single()
        return set(record["ids"]) if record and record["ids"] else set()


def _db_get_kp_names(kp_ids: List[str]) -> Dict[str, str]:
    """批量查询知识点名称（同步执行）

    Args:
        kp_ids: 知识点 ID 列表

    Returns:
        {knowledge_point_id: name}
    """
    if not kp_ids:
        return {}
    driver = get_driver()
    with driver.session() as session:
        result = session.run(
            "MATCH (k:KnowledgePoint) WHERE k.id IN $ids RETURN k.id AS id, k.name AS name",
            ids=kp_ids,
        )
        return {record["id"]: record["name"] for record in result}


# ==================== 异步服务接口 ====================


async def _ensure_kp_exist(kp_ids: List[str]) -> None:
    """校验关联知识点全部存在于 Neo4j

    Args:
        kp_ids: 关联知识点 ID 列表

    Raises:
        KnowledgePointMissingError: 存在 Neo4j 中查不到的知识点
    """
    existing = await asyncio.to_thread(_db_check_kp_exist, kp_ids)
    missing = [kp_id for kp_id in kp_ids if kp_id not in existing]
    if missing:
        raise KnowledgePointMissingError(missing)


async def list_questions(
    page: int = 1,
    page_size: int = 20,
    knowledge_point_id: Optional[str] = None,
    question_type: Optional[str] = None,
    difficulty_min: Optional[float] = None,
    difficulty_max: Optional[float] = None,
    keyword: Optional[str] = None,
) -> Tuple[List[QuestionListItem], int]:
    """分页查询题目列表

    Args:
        page: 页码，从 1 开始
        page_size: 每页条数
        knowledge_point_id: 按关联知识点筛选，None 表示不过滤
        question_type: 按题型筛选，None 表示不过滤
        difficulty_min: 难度下限（含），None 表示不过滤
        difficulty_max: 难度上限（含），None 表示不过滤
        keyword: 按题干模糊搜索，None 表示不过滤

    Returns:
        (当前页题目列表, 总数)

    Note:
        knowledge_point_names 来自 Neo4j；Neo4j 不可用时名称降级为
        空字符串（与 knowledge_point_ids 位置对齐）并记录 warning，
        不阻塞列表查询。
    """
    total, rows = await asyncio.to_thread(
        _db_list_page,
        page,
        page_size,
        knowledge_point_id,
        question_type,
        difficulty_min,
        difficulty_max,
        keyword,
    )

    # 批量查询 Q矩阵关联（SQL Server），失败降级为空列表
    kp_map: Dict[str, List[str]] = {}
    try:
        kp_map = await asyncio.to_thread(
            _db_get_question_kp_ids, [row["id"] for row in rows]
        )
    except Exception as e:
        logger.warning("查询题目知识点关联失败，knowledge_point_ids 降级为空: %s", e)

    # 批量查询知识点名称（Neo4j），失败降级为空字符串占位
    all_kp_ids = sorted({kp_id for kp_ids in kp_map.values() for kp_id in kp_ids})
    kp_names: Dict[str, str] = {}
    try:
        kp_names = await asyncio.to_thread(_db_get_kp_names, all_kp_ids)
    except Exception as e:
        logger.warning("查询知识点名称失败（Neo4j），knowledge_point_names 降级为空: %s", e)

    items = [
        QuestionListItem(
            id=row["id"],
            content=row["content"],
            type=row["type"],
            difficulty=row["difficulty"],
            knowledge_point_ids=kp_map.get(row["id"], []),
            # 名称与 ID 位置对齐，查不到的用空字符串占位
            knowledge_point_names=[
                kp_names.get(kp_id, "") for kp_id in kp_map.get(row["id"], [])
            ],
            created_at=row["created_at"],
        )
        for row in rows
    ]
    return items, total


async def get_question(question_id: str) -> Optional[QuestionDetail]:
    """查询单个题目详情（含选项和解析）

    Args:
        question_id: 题目 ID

    Returns:
        QuestionDetail 或 None（题目不存在）
    """
    data = await asyncio.to_thread(_db_get_question, question_id)
    if data is None:
        return None
    return QuestionDetail(**data)


async def create_question(
    content: str,
    question_type: str,
    difficulty: float,
    options: List[QuestionOption],
    answer: str,
    explanation: str,
    kp_ids: List[str],
) -> QuestionDetail:
    """新增题目（含 Q矩阵关联写入 q_matrix 表）

    关联知识点必须全部存在于 Neo4j，否则拒绝创建。

    Args:
        content: 题目题干
        question_type: 题型
        difficulty: 难度系数
        options: 选项列表（已通过 Pydantic 校验）
        answer: 正确答案
        explanation: 题目解析
        kp_ids: 关联知识点 ID 列表

    Returns:
        创建后的题目详情（含新生成的 id）

    Raises:
        KnowledgePointMissingError: 关联知识点不存在
    """
    await _ensure_kp_exist(kp_ids)
    question_id = _generate_question_id()
    options_json = options_to_json([opt.model_dump() for opt in options])
    data = await asyncio.to_thread(
        _db_create_question,
        question_id,
        content,
        question_type,
        difficulty,
        options_json,
        answer,
        explanation,
        kp_ids,
    )
    logger.info("题目创建成功: %s (type=%s, kp=%s)", question_id, question_type, kp_ids)
    return QuestionDetail(**data)


async def update_question(
    question_id: str,
    content: str,
    question_type: str,
    difficulty: float,
    options: List[QuestionOption],
    answer: str,
    explanation: str,
    kp_ids: List[str],
) -> Optional[QuestionDetail]:
    """编辑题目（同步更新 Q矩阵）

    Args:
        question_id: 题目 ID
        content: 新题干
        question_type: 新题型
        difficulty: 新难度系数
        options: 新选项列表
        answer: 新答案
        explanation: 新解析
        kp_ids: 新关联知识点 ID 列表

    Returns:
        更新后的题目详情；题目不存在时返回 None

    Raises:
        KnowledgePointMissingError: 关联知识点不存在
    """
    await _ensure_kp_exist(kp_ids)
    options_json = options_to_json([opt.model_dump() for opt in options])
    data = await asyncio.to_thread(
        _db_update_question,
        question_id,
        content,
        question_type,
        difficulty,
        options_json,
        answer,
        explanation,
        kp_ids,
    )
    if data is None:
        return None
    logger.info("题目更新成功: %s", question_id)
    return QuestionDetail(**data)


async def delete_question(question_id: str) -> None:
    """删除题目（同步删除 Q矩阵关联）

    Args:
        question_id: 题目 ID

    Raises:
        QuestionNotFoundError: 题目不存在
    """
    await asyncio.to_thread(_db_delete_question, question_id)
    logger.info("题目删除成功: %s", question_id)


async def batch_import_questions(questions: List[dict]) -> QuestionBatchImportResult:
    """批量导入题目，逐行独立处理并统计成功/失败

    流程：
    1. 一次性查询全部关联知识点在 Neo4j 中的存在性（单次查询）
    2. 逐行用 QuestionCreateRequest 做深度校验，失败记入 errors
    3. 校验通过的题目单独开事务写入（题目 + Q矩阵），失败不影响其他行

    Args:
        questions: 题目对象字典列表（结构同 POST 单个）

    Returns:
        QuestionBatchImportResult: success_count / fail_count / errors

    Note:
        单行失败不会导致整个请求失败，整体由 data 中的统计反映结果；
        Neo4j 异常会向上抛，由 router 统一返回 50002。
    """
    # 1. 知识点存在性（Neo4j 单次查询）
    all_kp_ids = sorted(
        {
            kp_id
            for raw in questions
            for kp_id in (raw.get("knowledge_point_ids") or [])
            if isinstance(kp_id, str) and kp_id
        }
    )
    existing = await asyncio.to_thread(_db_check_kp_exist, all_kp_ids)

    success_count = 0
    errors: List[QuestionImportError] = []
    for index, raw in enumerate(questions, start=1):
        # 2. 逐行深度校验（单行失败不阻塞其他行）
        try:
            item = QuestionCreateRequest.model_validate(raw)
        except ValidationError as exc:
            errors.append(
                QuestionImportError(row=index, message=first_validation_message(exc))
            )
            continue

        missing = [
            kp_id for kp_id in item.knowledge_point_ids if kp_id not in existing
        ]
        if missing:
            errors.append(
                QuestionImportError(
                    row=index, message="关联知识点不存在: " + ", ".join(missing)
                )
            )
            continue

        # 3. 写入题目 + Q矩阵（单行事务）
        question_id = _generate_question_id()
        options_json = options_to_json([opt.model_dump() for opt in item.options or []])
        try:
            await asyncio.to_thread(
                _db_create_question,
                question_id,
                item.content,
                item.type,
                item.difficulty,
                options_json,
                item.answer,
                item.explanation,
                item.knowledge_point_ids,
            )
            success_count += 1
        except Exception as e:
            logger.warning("批量导入第 %d 行写入失败: %s", index, e)
            errors.append(QuestionImportError(row=index, message="数据库写入失败"))

    logger.info("批量导入完成: 成功 %d 条，失败 %d 条", success_count, len(errors))
    return QuestionBatchImportResult(
        success_count=success_count,
        fail_count=len(errors),
        errors=errors,
    )
