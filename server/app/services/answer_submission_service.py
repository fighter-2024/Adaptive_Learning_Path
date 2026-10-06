"""
学员端答题提交业务服务

为学员端「答题」模块提供判题与掌握状态实时更新，数据职责严格按
AI开发总则第六条「数据库职责划分」，全部落 SQL Server：
- questions + q_matrix     → 取正确答案、题型、解析、关联知识点
- answer_records           → 写入每次作答记录（docs/数据库设计.md「1.5」）
- user_kp_mastery          → 实时更新掌握概率快照（docs/数据库设计.md「1.7」）

判题归一化规则（纯函数 judge_answer）：
- 单选：去除首尾空白后大小写不敏感比较（"b" 视为 "B"）
- 多选：按逗号拆分、去空白、大小写不敏感，排序后比较；重复或非法 label 判错
- 判断：true/false 大小写不敏感，同时兼容选项文案「对/错」

掌握概率更新（纯函数 bayesian_mastery_update）：
DINA 风格贝叶斯后验，依据总则第七条「贝叶斯后验推断使用上一轮 α 作为先验」
及契约 1.6 系统配置的 dina_s_initial / dina_g_initial（默认 0.2，读自 settings）：
- 答对：P(α=1|X=1) = p(1-s) / (p(1-s) + (1-p)g)
- 答错：P(α=1|X=0) = p·s / (p·s + (1-p)(1-g))
无掌握记录的知识点以 0.5 作为中性先验（DEFAULT_MASTERY_PRIOR）。
该实时更新是轻量快照；权威诊断仍由后续 DINA EM 诊断接口重算。

事务与批量语义：
- 单题：answer_records 插入 + user_kp_mastery 更新同一事务；
- 批量：题目不存在（含已下线）的项跳过并记 error（不阻塞其他项）；
  全部成功项在同一个事务中写入，任一步失败整体回滚 → 数据库异常由
  router 映射为 50001，客户端可安全重试；
- 批次内同一知识点多题时按顺序链式更新（后题的 before = 前题更新后的值）。

Service 层不接触 HTTP 对象，只处理业务数据；所有同步数据库操作通过
asyncio.to_thread 放入线程池执行，避免阻塞事件循环。
"""

import asyncio
import logging
import uuid
from typing import Dict, List, Optional, Sequence, Set, Tuple, Union

from app.config import settings
from app.db.sqlserver import get_connection
from app.models.answer_submission import (
    AnswerValue,
    AnswerSubmitRequest,
    BatchAnswerResult,
    MasteryChangeItem,
    SubmitAnswerResult,
    SubmitBatchResult,
    SubmitBatchSummary,
)
from app.services.question_service import json_to_options

logger = logging.getLogger(__name__)

# 无掌握记录时的中性先验（贝叶斯更新的起点）
DEFAULT_MASTERY_PRIOR = 0.5

# ==================== 业务异常 ====================
# Router 层捕获这些异常并映射为统一响应码，不向客户端暴露内部堆栈。


class QuestionNotFoundError(Exception):
    """题目不存在（含已下线）"""

    def __init__(self, question_id: str) -> None:
        self.question_id = question_id
        super().__init__(f"题目 {question_id} 不存在")


# ==================== 纯函数工具（便于单元测试） ====================


def _choice_parts(value: Union[str, Sequence[str]]) -> List[str]:
    """将多选答案拆分为规范化列表，保留重复项和空项。"""
    raw_parts = value.split(",") if isinstance(value, str) else list(value)
    return [part.strip().upper() for part in raw_parts]


def _split_choice_parts(value: Union[str, Sequence[str]]) -> Set[str]:
    """将多选答案拆分为集合（仅供兼容性调用，不用于判定合法性）。

    Args:
        value: 逗号分隔字符串或选项标识数组，如 "A, C"、"A,C" 或 ["A", "C"]

    Returns:
        规范化后的选项标识集合（空段被丢弃）
    """
    return {part for part in _choice_parts(value) if part}


def _normalize_true_false(value: str) -> str:
    """判断题答案归一化：true/false 大小写不敏感，兼容「对/错」文案

    题目表 answer 列存储 "true"/"false"（见 QuestionCreateRequest 校验），
    但学生端展示的选项文案是「对/错」，故此处兼容两种写法。

    Args:
        value: 学生提交或题库存储的答案

    Returns:
        归一化后的 "true" / "false"；无法识别时原样返回
    """
    stripped = value.strip()
    upper = stripped.upper()
    if upper in ("TRUE", "FALSE"):
        return upper.lower()
    return {"对": "true", "错": "false"}.get(stripped, stripped)


def judge_answer(
    question_type: str,
    correct_answer: str,
    student_answer: Union[str, Sequence[str]],
    valid_labels: Optional[Sequence[str]] = None,
) -> bool:
    """判题：按题型归一化后比较学生答案与正确答案

    规则（与模块 docstring 一致）：
    - multi_choice: 排序后比较（顺序、大小写、空格不敏感）；重复、空段和
      非法选项均判错，不能通过集合去重被忽略
    - true_false: true/false 与「对/错」等价（大小写不敏感）
    - single_choice 及其他: 去空白后大小写不敏感比较

    Args:
        question_type: 题型 single_choice / multi_choice / true_false
        correct_answer: 题库正确答案（questions.answer）
        student_answer: 学生提交的答案

    Returns:
        True 表示答对
    """
    if question_type == "multi_choice":
        correct_parts = _choice_parts(correct_answer)
        student_parts = _choice_parts(student_answer)
        labels = {label.strip().upper() for label in (valid_labels or [])}
        if (
            not correct_parts
            or not student_parts
            or any(not part for part in correct_parts + student_parts)
            or len(student_parts) != len(set(student_parts))
            or (labels and any(part not in labels for part in student_parts))
        ):
            return False
        return sorted(student_parts) == sorted(correct_parts)
    if question_type == "true_false":
        if not isinstance(student_answer, str):
            return False
        return _normalize_true_false(correct_answer) == _normalize_true_false(student_answer)
    if not isinstance(student_answer, str):
        return False
    if valid_labels:
        labels = {label.strip().upper() for label in valid_labels}
        if student_answer.strip().upper() not in labels:
            return False
    return correct_answer.strip().upper() == student_answer.strip().upper()


def normalize_student_answer(
    question_type: str, student_answer: Union[str, Sequence[str]]
) -> str:
    """把学生答案规范化为 answer_records 可审计的字符串。

    该函数只清理空白、统一大小写和分隔表示；不会去重或删除非法 label，
    从而保留重复点击、漏选和非法输入等真实作答证据。
    """
    if question_type == "multi_choice":
        return ",".join(_choice_parts(student_answer))
    if not isinstance(student_answer, str):
        return ",".join(_choice_parts(student_answer))
    if question_type == "true_false":
        return _normalize_true_false(student_answer)
    return student_answer.strip().upper()


def response_correct_answer(question_type: str, correct_answer: str) -> Union[str, List[str]]:
    """按题型构造对学生展示的正确答案。"""
    if question_type == "multi_choice":
        return sorted(_choice_parts(correct_answer))
    if question_type == "true_false":
        return _normalize_true_false(correct_answer)
    return correct_answer.strip().upper()


def bayesian_mastery_update(
    before: float,
    is_correct: bool,
    slip: float = 0.2,
    guess: float = 0.2,
) -> float:
    """DINA 风格贝叶斯后验更新知识点掌握概率

    以作答前的掌握概率为先验，失误率 s / 猜测率 g 为似然参数：
    - 答对: P(α=1|X=1) = p(1-s) / (p(1-s) + (1-p)g)
    - 答错: P(α=1|X=0) = p·s / (p·s + (1-p)(1-g))
    先验钳制在 [0, 1]；结果四舍五入到 6 位小数，保证接口数值稳定。

    Args:
        before: 作答前的掌握概率（先验）
        is_correct: 本次是否答对
        slip: 失误率 s（已掌握仍答错的概率），默认 0.2
        guess: 猜测率 g（未掌握仍猜对的概率），默认 0.2

    Returns:
        更新后的掌握概率（0.0 ~ 1.0）
    """
    p = min(1.0, max(0.0, before))
    if is_correct:
        numerator = p * (1.0 - slip)
        denominator = numerator + (1.0 - p) * guess
    else:
        numerator = p * slip
        denominator = numerator + (1.0 - p) * (1.0 - guess)
    if denominator <= 0.0:
        # 数值兜底：仅在退化参数组合（s=0 且 g=0 且 p=0）时触发，返回先验
        return p
    return round(numerator / denominator, 6)


def _generate_record_id() -> str:
    """生成答题记录业务 ID

    Returns:
        形如 ar_xxxxxxxx 的 ID（8 位十六进制，对照数据库设计 ID 命名规范）
    """
    return f"ar_{uuid.uuid4().hex[:8]}"


# ==================== SQL Server 同步操作（线程池执行） ====================


def _db_load_questions(question_ids: List[str]) -> Dict[str, dict]:
    """批量查询启用中的题目判题要素（同步执行）

    Args:
        question_ids: 题目 ID 列表（可重复）

        Returns:
        {question_id: {type, answer, explanation, options}}；
        不存在或已下线（is_active=0）的题目不在结果中
    """
    if not question_ids:
        return {}
    placeholders = ", ".join(["?"] * len(question_ids))
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT question_id, type, answer, explanation, options FROM questions "
            f"WHERE question_id IN ({placeholders}) AND is_active = 1",
            tuple(question_ids),
        )
        return {
            row[0]: {
                "type": row[1],
                "answer": row[2],
                "explanation": row[3] or "",
                "options": json_to_options(row[4]),
            }
            for row in cursor.fetchall()
        }
    finally:
        conn.close()


def _db_load_question_kp_ids(question_ids: List[str]) -> Dict[str, List[str]]:
    """从 q_matrix 批量查询题目关联的知识点 ID（同步执行）

    Args:
        question_ids: 题目 ID 列表

    Returns:
        {question_id: [knowledge_point_id, ...]}（按 q_matrix 插入顺序）
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


def _db_load_mastery_rows(user_id: str, kp_ids: List[str]) -> Dict[str, dict]:
    """批量查询学员知识点掌握快照（同步执行）

    Args:
        user_id: 学生业务 ID
        kp_ids: 知识点 ID 列表

    Returns:
        {knowledge_point_id: {mastery_probability, questions_done, correct_count}}；
        无记录的知识点不在结果中
    """
    if not kp_ids:
        return {}
    placeholders = ", ".join(["?"] * len(kp_ids))
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT knowledge_point_id, mastery_probability, questions_done, correct_count "
            f"FROM user_kp_mastery "
            f"WHERE user_id = ? AND knowledge_point_id IN ({placeholders})",
            (user_id, *kp_ids),
        )
        return {
            row[0]: {
                "mastery_probability": float(row[1]),
                "questions_done": int(row[2]),
                "correct_count": int(row[3]),
            }
            for row in cursor.fetchall()
        }
    finally:
        conn.close()


def _db_apply_submissions(
    user_id: str,
    records: List[dict],
    kp_updates: Dict[str, dict],
) -> None:
    """写入答题记录并更新掌握快照（同一事务，同步执行）

    answer_records 逐条插入；user_kp_mastery 按最终值 upsert
    （有记录 UPDATE，无记录 INSERT，updated_at 取数据库当前时间）。
    任一步失败整体回滚，保证「记录已写但掌握未更新」的半提交状态不会出现。

    Args:
        user_id: 学生业务 ID
        records: 待写入的答题记录列表，元素含 record_id / question_id /
            student_answer / is_correct / time_spent
        kp_updates: 知识点最终快照 {knowledge_point_id:
            {mastery_probability, questions_done, correct_count}}

    Raises:
        pyodbc.Error 等数据库异常: 事务回滚后向上抛，由 router 映射为 50001
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        for record in records:
            cursor.execute(
                "INSERT INTO answer_records "
                "(record_id, user_id, question_id, student_answer, is_correct, time_spent) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record["record_id"],
                    user_id,
                    record["question_id"],
                    record["student_answer"],
                    1 if record["is_correct"] else 0,
                    record["time_spent"],
                ),
            )
        for kp_id, update in kp_updates.items():
            cursor.execute(
                "UPDATE user_kp_mastery "
                "SET mastery_probability = ?, questions_done = ?, correct_count = ?, "
                "updated_at = GETDATE() "
                "WHERE user_id = ? AND knowledge_point_id = ?",
                (
                    update["mastery_probability"],
                    update["questions_done"],
                    update["correct_count"],
                    user_id,
                    kp_id,
                ),
            )
            # rowcount 可能为 -1（驱动未报告），此时再查一次确认行是否存在
            if cursor.rowcount == 0:
                exists = cursor.execute(
                    "SELECT 1 FROM user_kp_mastery "
                    "WHERE user_id = ? AND knowledge_point_id = ?",
                    (user_id, kp_id),
                ).fetchone()
                if exists is None:
                    cursor.execute(
                        "INSERT INTO user_kp_mastery "
                        "(user_id, knowledge_point_id, mastery_probability, "
                        "questions_done, correct_count) VALUES (?, ?, ?, ?, ?)",
                        (
                            user_id,
                            kp_id,
                            update["mastery_probability"],
                            update["questions_done"],
                            update["correct_count"],
                        ),
                    )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ==================== 异步服务接口 ====================


async def _process_submissions(
    user_id: str,
    answers: List[AnswerSubmitRequest],
) -> Tuple[List[BatchAnswerResult], SubmitBatchSummary]:
    """提交答案核心流程：判题 → 掌握概率链式更新 → 事务写入

    步骤：
    1. 批量加载题目判题要素、Q矩阵关联、掌握快照（各一次查询）；
    2. 按提交顺序逐题判题，工作副本内链式更新掌握概率（同知识点
       在批次内多题时，后题的 before 取前题更新后的值）；
    3. 成功项（题目存在的题）在一个事务中写入 answer_records 与
       user_kp_mastery；题目不存在的项记 error 跳过，不阻塞其他项。

    Args:
        user_id: 学生业务 ID
        answers: 待提交的答案列表（Pydantic 已校验非空）

    Returns:
        (每题判题结果列表, 汇总统计)

    Raises:
        pyodbc.Error 等数据库异常: 事务回滚后向上抛
    """
    question_ids = [answer.question_id for answer in answers]

    # 1. 批量加载（各一次数据库往返）
    question_map = await asyncio.to_thread(_db_load_questions, question_ids)
    kp_map = await asyncio.to_thread(
        _db_load_question_kp_ids, list(question_map.keys())
    )
    all_kp_ids = sorted({kp_id for kps in kp_map.values() for kp_id in kps})
    mastery_rows: Dict[str, dict] = {}
    if all_kp_ids:
        mastery_rows = await asyncio.to_thread(
            _db_load_mastery_rows, user_id, all_kp_ids
        )

    # 2. 工作副本：批次内顺序链式更新掌握概率
    working: Dict[str, dict] = {
        kp_id: {
            "probability": row["mastery_probability"],
            "done": row["questions_done"],
            "correct": row["correct_count"],
        }
        for kp_id, row in mastery_rows.items()
    }

    records: List[dict] = []
    kp_finals: Dict[str, dict] = {}
    results: List[BatchAnswerResult] = []

    for answer in answers:
        question = question_map.get(answer.question_id)
        if question is None:
            results.append(
                BatchAnswerResult(question_id=answer.question_id, error="题目不存在")
            )
            continue

        option_labels = [option["label"] for option in question.get("options", [])]
        correct = judge_answer(
            question["type"],
            question["answer"],
            answer.student_answer,
            valid_labels=option_labels,
        )
        changes: Dict[str, MasteryChangeItem] = {}
        for kp_id in kp_map.get(answer.question_id, []):
            state = working.get(kp_id)
            if state is None:
                # 该知识点无掌握记录：以中性先验起步
                state = working[kp_id] = {
                    "probability": DEFAULT_MASTERY_PRIOR,
                    "done": 0,
                    "correct": 0,
                }
            before = state["probability"]
            after = bayesian_mastery_update(
                before, correct, settings.DINA_S_INITIAL, settings.DINA_G_INITIAL
            )
            state["probability"] = after
            state["done"] += 1
            state["correct"] += 1 if correct else 0
            changes[kp_id] = MasteryChangeItem(
                before=round(before, 6), after=round(after, 6)
            )
            kp_finals[kp_id] = {
                "mastery_probability": after,
                "questions_done": state["done"],
                "correct_count": state["correct"],
            }

        records.append(
            {
                "record_id": _generate_record_id(),
                "question_id": answer.question_id,
                "student_answer": normalize_student_answer(
                    question["type"], answer.student_answer
                ),
                "is_correct": correct,
                "time_spent": answer.time_spent,
            }
        )
        results.append(
            BatchAnswerResult(
                question_id=answer.question_id,
                correct=correct,
                correct_answer=response_correct_answer(
                    question["type"], question["answer"]
                ),
                explanation=question["explanation"],
                mastery_change=changes,
            )
        )

    # 3. 成功项统一事务写入（失败整体回滚，可安全重试）
    if records:
        await asyncio.to_thread(_db_apply_submissions, user_id, records, kp_finals)
        logger.info(
            "答题提交完成: user_id=%s, 提交 %d 题, 写入记录 %d 条, 更新知识点 %d 个",
            user_id,
            len(answers),
            len(records),
            len(kp_finals),
        )

    graded = [result for result in results if result.error is None]
    correct_count = sum(1 for result in graded if result.correct)
    summary = SubmitBatchSummary(
        total=len(results),
        correct_count=correct_count,
        wrong_count=len(graded) - correct_count,
        fail_count=len(results) - len(graded),
        correct_rate=round(correct_count / len(graded), 4) if graded else 0.0,
    )
    return results, summary


async def submit_answer(
    user_id: str,
    question_id: str,
    student_answer: AnswerValue,
    time_spent: Optional[int],
) -> SubmitAnswerResult:
    """提交单题答案：判题 + 更新掌握概率 + 写入答题记录

    Args:
        user_id: 学生业务 ID
        question_id: 题目 ID
        student_answer: 学生提交的答案
        time_spent: 答题耗时（秒），可为 None

    Returns:
        SubmitAnswerResult: correct / correct_answer / explanation / mastery_change

    Raises:
        QuestionNotFoundError: 题目不存在或已下线
    """
    results, _ = await _process_submissions(
        user_id,
        [
            AnswerSubmitRequest(
                question_id=question_id,
                student_answer=student_answer,
                time_spent=time_spent,
            )
        ],
    )
    item = results[0]
    if item.error is not None:
        raise QuestionNotFoundError(question_id)
    return SubmitAnswerResult(
        correct=item.correct,  # type: ignore[arg-type]
        correct_answer=item.correct_answer if item.correct_answer is not None else "",
        explanation=item.explanation or "",
        mastery_change=item.mastery_change,
    )


async def submit_batch(
    user_id: str,
    answers: List[AnswerSubmitRequest],
) -> SubmitBatchResult:
    """批量提交答案：逐题判题并返回每题结果与汇总统计

    题目不存在（含已下线）的项记 error 跳过，不阻塞其他项；
    全部成功项在同一事务写入，数据库异常整体回滚由 router 映射为 50001。

    Args:
        user_id: 学生业务 ID
        answers: 答案数组（每项结构同 submit-answer）

    Returns:
        SubmitBatchResult: results（每题判题结果）+ summary（汇总统计）
    """
    results, summary = await _process_submissions(user_id, answers)
    return SubmitBatchResult(results=results, summary=summary)
