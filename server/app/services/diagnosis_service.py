"""
DINA 认知诊断 — 学员诊断业务服务

为学员端「诊断」模块提供完整流程，严格对照 docs/API契约文档.md
「2.3 诊断」POST /api/student/diagnosis 与 AI开发总则第七条 DINA 约束：

1. Q 矩阵管理：从 SQL Server q_matrix 表加载题目-知识点关联
   （总则第六条：Q 矩阵存 SQL Server）；
2. EM 估计题目参数（失误率 s、猜测率 g）：以当前学生按策略聚合后的
   答题记录为样本，迭代上限/收敛阈值/初始值读取自 config
   （DINA_EM_MAX_ITERATIONS / DINA_EM_CONVERGENCE_THRESHOLD /
   DINA_S_INITIAL / DINA_G_INITIAL）；
3. 贝叶斯后验推断：以该学生上一轮 α（user_kp_mastery 快照）为先验
   （总则第七条），推断知识掌握向量 α（维度 = Q 矩阵知识点总数）；
4. 诊断结果写入 diagnosis_sessions（每次诊断一条，保留进步轨迹）；
5. 同步更新 user_kp_mastery 快照：掌握概率取后验值，做题数/正确数
   从 answer_records × q_matrix 重算（幂等，与答题提交服务的增量
   计数口径一致）。仅更新有作答证据的知识点，无证据知识点保持
   not_started 语义不被污染。

纯 Python 实现，不依赖任何外部 ML 库。所有同步数据库操作经
asyncio.to_thread 放入线程池执行；Service 层不接触 HTTP 对象。
"""

import asyncio
import inspect
import json
import logging
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from app.config import settings
from app.db.sqlserver import get_connection, get_local_now
from app.models.diagnosis import DiagnosisResult, DiagnosisTrace
from app.services.dina import (
    QMatrix,
    QMatrixError,
    estimate_item_parameters,
    infer_mastery_posterior,
)
from app.services.dina.inference import NEUTRAL_PRIOR

logger = logging.getLogger(__name__)

DINA_ALGORITHM_VERSION = "dina-v1"
DINA_PARAMETER_VERSION = "default-v1"
DINA_REPEAT_STRATEGY = "latest_attempt"


@dataclass(frozen=True)
class AnswerAttempt:
    """一条答题尝试的最小诊断字段。

    诊断只需要学生、题目、对错和排序字段，不读取答案正文、耗时等无关
    数据。``record_order`` 用于 created_at 相同或旧测试没有时间戳时稳定
    地决定“最新”记录。
    """

    user_id: str
    question_id: str
    is_correct: bool
    created_at: Optional[datetime] = None
    record_order: int = 0


class InsufficientAnswerError(Exception):
    """答题记录不足，无法诊断（无有效答题记录或 Q 矩阵无数据）"""


# ==================== SQL Server 同步操作（线程池执行） ====================


def _db_load_qmatrix_rows() -> List[Tuple[str, str]]:
    """从 q_matrix 表加载题目-知识点关联行（同步执行）

    Returns:
        (question_id, knowledge_point_id) 列表，按插入顺序
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT question_id, knowledge_point_id FROM q_matrix ORDER BY id"
        )
        return [(row[0], row[1]) for row in cursor.fetchall()]
    finally:
        conn.close()


def _db_load_all_answer_records(user_id: str) -> List[AnswerAttempt]:
    """加载当前学生的诊断必要字段（同步执行）。

    M7 固定使用当前学生的最新一次作答作为诊断观测，避免每次诊断扫描
    无关用户的全部历史。题目参数 EM 与在线掌握度更新都从同一配置初值
    出发；单学生样本不足时仍返回可追踪的非收敛状态，而不是伪造队列数据。

    Args:
        user_id: 当前学生业务 ID。

    Returns:
        ``AnswerAttempt`` 列表，按答题时间和自增 ID 升序排列。
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, question_id, is_correct, created_at "
            "FROM answer_records "
            "WHERE user_id = ? "
            "ORDER BY created_at ASC, id ASC",
            (user_id,),
        )
        return [
            AnswerAttempt(
                user_id=user_id,
                question_id=row[1],
                is_correct=bool(row[2]),
                created_at=row[3],
                record_order=int(row[0]),
            )
            for row in cursor.fetchall()
        ]
    finally:
        conn.close()


def _db_load_mastery_rows(
    user_id: str, attribute_ids: List[str]
) -> List[Tuple[str, str, float]]:
    """加载当前学生、当前 Q 矩阵属性的掌握快照（同步执行）。

    Returns:
        (user_id, knowledge_point_id, mastery_probability) 列表
    """
    if not attribute_ids:
        return []
    placeholders = ", ".join(["?"] * len(attribute_ids))
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, knowledge_point_id, mastery_probability "
            "FROM user_kp_mastery "
            f"WHERE user_id = ? AND knowledge_point_id IN ({placeholders})",
            (user_id, *attribute_ids),
        )
        return [(row[0], row[1], float(row[2])) for row in cursor.fetchall()]
    finally:
        conn.close()


def _db_load_latest_diagnosis(user_id: str) -> Optional[DiagnosisResult]:
    """读取当前学生最近一次诊断结果（同步执行）。"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT TOP 1 alpha_vector, question_count, diagnosed_at, "
            "algorithm_version, parameter_version, answer_time_from, "
            "answer_time_to, repeat_strategy, converged, iterations "
            "FROM diagnosis_sessions "
            "WHERE user_id = ? "
            "ORDER BY diagnosed_at DESC, id DESC",
            (user_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        row_values = tuple(row)
        trace = _restore_diagnosis_trace(row_values)
        # 兼容 0002 前的旧适配器：它仍可能只返回 alpha_vector、diagnosed_at。
        diagnosed_at_index = 2 if len(row_values) >= 3 else 1
        return DiagnosisResult(
            alpha_vector=json.loads(row_values[0]),
            diagnosed_at=_format_answer_time(row_values[diagnosed_at_index]) or "",
            trace=trace,
        )
    finally:
        conn.close()


def _db_load_kp_statistics(user_id: str, kp_ids: List[str]) -> Dict[str, dict]:
    """按知识点统计该学生的做题数与正确数（同步执行）

    从 answer_records × q_matrix 联表重算（幂等）：一道多知识点题
    对每个知识点各计一次，与答题提交服务的增量计数口径一致。

    Args:
        user_id: 学生业务 ID
        kp_ids: 知识点 ID 列表

    Returns:
        {knowledge_point_id: {questions_done, correct_count}}
    """
    if not kp_ids:
        return {}
    placeholders = ", ".join(["?"] * len(kp_ids))
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT m.knowledge_point_id, COUNT(*), "
            f"SUM(CASE WHEN ar.is_correct = 1 THEN 1 ELSE 0 END) "
            f"FROM answer_records ar "
            f"INNER JOIN q_matrix m ON m.question_id = ar.question_id "
            f"WHERE ar.user_id = ? AND m.knowledge_point_id IN ({placeholders}) "
            f"GROUP BY m.knowledge_point_id",
            (user_id, *kp_ids),
        )
        return {
            row[0]: {"questions_done": int(row[1]), "correct_count": int(row[2])}
            for row in cursor.fetchall()
        }
    finally:
        conn.close()


def _db_save_diagnosis(
    session_id: str,
    user_id: str,
    alpha_vector_json: str,
    question_count: int,
    diagnosed_at: datetime,
    kp_updates: Dict[str, dict],
    trace: Optional[DiagnosisTrace] = None,
) -> None:
    """写入诊断会话并更新掌握快照（同一事务，同步执行）

    diagnosis_sessions 插入一条诊断记录；user_kp_mastery 按知识点
    upsert（有记录 UPDATE 掌握概率与计数并刷新 updated_at，
    无记录 INSERT）。任一步失败整体回滚，保证不会出现
    「诊断已保存但掌握快照未更新」的半提交状态。

    Args:
        session_id: 诊断会话业务 ID（diag_ 前缀）
        user_id: 学生业务 ID
        alpha_vector_json: α 向量 JSON 字符串（{知识点ID: 掌握概率}）
        question_count: 用于本次诊断的答题数
        diagnosed_at: 诊断完成时间
        kp_updates: {knowledge_point_id: {mastery_probability,
            questions_done, correct_count}}
        trace: 诊断追踪字段；迁移 0002 后写入诊断会话

    Raises:
        pyodbc.Error 等数据库异常: 事务回滚后向上抛，由 router 映射为 50001
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        if trace is None:
            # 兼容尚未应用 0002 的旧调用方；正式诊断总是传 trace。
            cursor.execute(
                "INSERT INTO diagnosis_sessions "
                "(session_id, user_id, alpha_vector, question_count, diagnosed_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    session_id,
                    user_id,
                    alpha_vector_json,
                    question_count,
                    diagnosed_at,
                ),
            )
        else:
            cursor.execute(
                "INSERT INTO diagnosis_sessions "
                "(session_id, user_id, alpha_vector, question_count, diagnosed_at, "
                "algorithm_version, parameter_version, answer_time_from, "
                "answer_time_to, repeat_strategy, converged, iterations) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    user_id,
                    alpha_vector_json,
                    question_count,
                    diagnosed_at,
                    trace.algorithm_version,
                    trace.parameter_version,
                    _parse_trace_time(trace.answer_time_from),
                    _parse_trace_time(trace.answer_time_to),
                    trace.repeat_strategy,
                    trace.converged,
                    trace.iterations,
                ),
            )
        for kp_id, update in kp_updates.items():
            cursor.execute(
                "UPDATE user_kp_mastery "
                "SET mastery_probability = ?, questions_done = ?, "
                "correct_count = ?, updated_at = GETDATE() "
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


# ==================== 纯函数工具 ====================


def _parse_trace_time(value: Optional[str]) -> Optional[datetime]:
    """将 API trace 的 ISO 时间转换为 SQL Server 可写入的时间。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except (TypeError, ValueError):
        return None


def _format_answer_time(value: object) -> Optional[str]:
    """以秒精度输出答题/诊断时间，兼容 pyodbc 和测试字符串。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat()
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    return parsed.replace(microsecond=0).isoformat()


def _coerce_datetime(value: object) -> Optional[datetime]:
    """归一化答题时间，避免时区感知/无时区值比较时报错。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return _parse_trace_time(str(value))


def _coerce_bool(value: object) -> bool:
    """把数据库/测试中的布尔值安全归一化。"""
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "n"}
    return bool(value)


def _restore_diagnosis_trace(row: object) -> Optional[DiagnosisTrace]:
    """从 0002 诊断行恢复 trace，并识别迁移前的历史记录。

    0002 给旧行的 ``algorithm_version``、``parameter_version``、
    ``repeat_strategy``、``converged`` 和 ``iterations`` 都写入了默认值，
    因此不能仅凭这些字段把旧记录伪装成有追踪信息。正式新诊断一定有
    至少一条答题，且服务会保存非空的答题时间范围；只有同时具备正数
    ``question_count`` 和完整的 ``answer_time_from/to`` 才恢复 trace。
    旧数据库/旧测试可能仍只返回 alpha 和 diagnosed_at，长度不足时继续
    按历史兼容路径返回空 trace。
    """
    values = tuple(row)  # type: ignore[arg-type]
    if len(values) < 10:
        return None
    answer_count = values[1]
    answer_time_from = _format_answer_time(values[5])
    answer_time_to = _format_answer_time(values[6])
    if not answer_time_from or not answer_time_to:
        return None
    try:
        answer_count = int(answer_count)
        iterations = int(values[9])
    except (TypeError, ValueError):
        return None
    if answer_count <= 0 or iterations < 0:
        return None

    algorithm_version = str(values[3] or "").strip()
    parameter_version = str(values[4] or "").strip()
    repeat_strategy = str(values[7] or "").strip()
    if not algorithm_version or not parameter_version:
        return None
    try:
        return DiagnosisTrace(
            algorithm_version=algorithm_version,
            parameter_version=parameter_version,
            answer_count=answer_count,
            answer_time_from=answer_time_from,
            answer_time_to=answer_time_to,
            repeat_strategy=repeat_strategy,
            converged=_coerce_bool(values[8]),
            iterations=iterations,
        )
    except ValueError:
        # 保持历史兼容：未来出现未知策略或脏 trace 时，不影响 alpha/time 恢复。
        return None


def _normalize_answer_attempt(raw: object, record_order: int) -> AnswerAttempt:
    """兼容数据库对象和旧测试三元组，统一为 ``AnswerAttempt``。"""
    if isinstance(raw, AnswerAttempt):
        return raw
    values = tuple(raw)  # type: ignore[arg-type]
    if len(values) >= 5:
        # 数据库原始行：id, user_id, question_id, is_correct, created_at。
        return AnswerAttempt(
            user_id=str(values[1]),
            question_id=str(values[2]),
            is_correct=_coerce_bool(values[3]),
            created_at=_coerce_datetime(values[4]),
            record_order=int(values[0]) if str(values[0]).isdigit() else record_order,
        )
    if len(values) == 4:
        # 测试/适配器格式：user_id, question_id, is_correct, created_at。
        return AnswerAttempt(
            user_id=str(values[0]),
            question_id=str(values[1]),
            is_correct=_coerce_bool(values[2]),
            created_at=_coerce_datetime(values[3]),
            record_order=record_order,
        )
    if len(values) == 3:
        # 旧测试格式：user_id, question_id, is_correct；顺序作为破局依据。
        return AnswerAttempt(
            user_id=str(values[0]),
            question_id=str(values[1]),
            is_correct=_coerce_bool(values[2]),
            record_order=record_order,
        )
    raise ValueError("答题记录字段不足，无法进行诊断")


def aggregate_latest_attempts(
    records: Iterable[object], user_id: str
) -> List[AnswerAttempt]:
    """按 ``latest_attempt`` 策略聚合当前学生的重复作答。

    同一题的每次提交都会保留在 ``answer_records``；诊断观测只取
    ``created_at`` 最大的一次，时间相同取自增 ``id`` 最大的一次。该行为
    是显式的重复作答策略，不是无说明的字典覆盖；所有原始尝试仍用于
    ``questions_done`` / ``correct_count`` 的统计。

    Args:
        records: 数据库记录或兼容的测试元组。
        user_id: 当前学生 ID，其他学生记录会被隔离。

    Returns:
        按时间和题目 ID 稳定排序的去重观测。
    """
    latest: Dict[str, AnswerAttempt] = {}
    for order, raw in enumerate(records):
        attempt = _normalize_answer_attempt(raw, order)
        if attempt.created_at is not None or attempt.record_order == 0:
            attempt = replace(
                attempt,
                created_at=_coerce_datetime(attempt.created_at),
                record_order=attempt.record_order if attempt.record_order else order,
            )
        if attempt.user_id != user_id:
            continue
        previous = latest.get(attempt.question_id)
        if previous is None or (
            attempt.created_at or datetime.min,
            attempt.record_order,
        ) > (
            previous.created_at or datetime.min,
            previous.record_order,
        ):
            latest[attempt.question_id] = attempt
    return sorted(
        latest.values(),
        key=lambda item: (
            item.created_at or datetime.min,
            item.record_order,
            item.question_id,
        ),
    )


def _call_compat_loader(
    loader: Callable[..., object], *args: object
) -> object:
    """让现有无参测试替身兼容新的按学生查询函数签名。"""
    try:
        parameters = list(inspect.signature(loader).parameters.values())
    except (TypeError, ValueError):
        return loader(*args)
    positional = [
        parameter
        for parameter in parameters
        if parameter.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in parameters):
        return loader(*args)
    return loader(*args[: len(positional)])


def _generate_session_id() -> str:
    """生成诊断会话业务 ID

    Returns:
        形如 diag_xxxxxxxx 的 ID（8 位十六进制，对照数据库设计 ID 命名规范）
    """
    return f"diag_{uuid.uuid4().hex[:8]}"


def _build_cohort_priors(
    mastery_rows: List[Tuple[str, str, float]],
    attribute_ids: List[str],
) -> List[float]:
    """构建 EM 类先验的边际概率：全体学生掌握概率均值，无数据取 0.5

    Args:
        mastery_rows: 全部用户知识点掌握快照行
        attribute_ids: Q 矩阵知识点 ID 列表（列顺序）

    Returns:
        与 attribute_ids 同序的先验边际概率列表
    """
    sums: Dict[str, float] = {}
    counts: Dict[str, int] = {}
    for _, kp_id, probability in mastery_rows:
        if kp_id not in attribute_ids:
            continue
        sums[kp_id] = sums.get(kp_id, 0.0) + probability
        counts[kp_id] = counts.get(kp_id, 0) + 1
    return [
        round(sums[kp_id] / counts[kp_id], 6)
        if counts.get(kp_id)
        else NEUTRAL_PRIOR
        for kp_id in attribute_ids
    ]


def _build_student_prior(
    user_id: str,
    mastery_rows: List[Tuple[str, str, float]],
    attribute_ids: List[str],
) -> List[float]:
    """构建该学生上一轮 α 作为贝叶斯先验（总则第七条），无记录取 0.5

    Args:
        user_id: 学生业务 ID
        mastery_rows: 全部用户知识点掌握快照行
        attribute_ids: Q 矩阵知识点 ID 列表（列顺序）

    Returns:
        与 attribute_ids 同序的先验边际概率列表
    """
    student_map = {
        kp_id: probability
        for u, kp_id, probability in mastery_rows
        if u == user_id
    }
    return [
        student_map.get(kp_id, NEUTRAL_PRIOR) for kp_id in attribute_ids
    ]


# ==================== 异步服务接口 ====================


async def diagnose_student(user_id: str) -> DiagnosisResult:
    """对学生执行一次完整的 DINA 认知诊断

    流程：加载 Q 矩阵与当前学生必要答题字段 → 按最近一次作答聚合
    → EM 估计题目参数 s/g → 以该学生上一轮 α 为先验做贝叶斯后验推断
    → 结果写入 diagnosis_sessions 并同步更新 user_kp_mastery。

    Args:
        user_id: 学生业务 ID

    Returns:
        DiagnosisResult: alpha_vector（维度 = Q 矩阵知识点总数，
            无作答证据的知识点保持先验值）+ diagnosed_at

    Raises:
        InsufficientAnswerError: Q 矩阵无数据，或该学生无有效答题记录
            （无任何作答，或作答题目均无 Q 矩阵关联）
    """
    # 1. 加载 Q 矩阵；答题和掌握数据均限定为当前学生。
    qmatrix_rows = await asyncio.to_thread(_db_load_qmatrix_rows)
    if not qmatrix_rows:
        raise InsufficientAnswerError("Q 矩阵无数据，无法进行认知诊断")

    try:
        qmatrix = QMatrix(qmatrix_rows)
    except (QMatrixError, TypeError, ValueError) as e:
        logger.error("Q 矩阵构造失败: %s", e)
        raise InsufficientAnswerError("Q 矩阵数据异常，无法进行认知诊断") from e

    # 防御性校验：总则第七条要求 Q 矩阵每题至少对应一个知识点
    # （构造上已保证，此处显式校验并映射为业务码 40002，避免 500）
    try:
        qmatrix.validate()
    except QMatrixError as e:
        logger.error("Q 矩阵校验失败: %s", e)
        raise InsufficientAnswerError("Q 矩阵数据异常，无法进行认知诊断")

    raw_answer_records = await asyncio.to_thread(
        _call_compat_loader, _db_load_all_answer_records, user_id
    )
    normalized_records = [
        _normalize_answer_attempt(raw, order)
        for order, raw in enumerate(raw_answer_records)  # type: ignore[arg-type]
    ]
    usable = [
        record
        for record in normalized_records
        if record.user_id == user_id and qmatrix.has_question(record.question_id)
    ]
    excluded = len(normalized_records) - len(usable)
    if excluded:
        logger.warning(
            "共 %d 条答题记录因题目无 Q 矩阵关联被排除，不参与诊断", excluded
        )

    # M7 重复作答策略：latest_attempt。原始记录不被删除，只有 DINA
    # 观测按题目聚合；统计计数继续由联表查询保留每次 attempt。
    student_records = aggregate_latest_attempts(usable, user_id)
    if not student_records:
        raise InsufficientAnswerError(
            f"学生 {user_id} 无有效答题记录，无法诊断"
        )

    # 只使用当前学生的聚合观测，避免为一次学生诊断加载无关用户数据。
    by_user: Dict[str, Dict[int, int]] = {
        user_id: {
            qmatrix.question_index(record.question_id): int(record.is_correct)
            for record in student_records
        }
    }
    mastery_rows_raw = await asyncio.to_thread(
        _call_compat_loader,
        _db_load_mastery_rows,
        user_id,
        qmatrix.attribute_ids,
    )
    mastery_rows = list(mastery_rows_raw)  # type: ignore[arg-type]
    cohort_priors = _build_cohort_priors(mastery_rows, qmatrix.attribute_ids)
    student_prior = _build_student_prior(user_id, mastery_rows, qmatrix.attribute_ids)

    # 3. EM 估计题目参数（CPU 密集，放线程池，参数读取自 config）
    em_result = await asyncio.to_thread(
        estimate_item_parameters,
        list(by_user.values()),
        qmatrix,
        cohort_priors,
        s_init=settings.DINA_S_INITIAL,
        g_init=settings.DINA_G_INITIAL,
        max_iterations=settings.DINA_EM_MAX_ITERATIONS,
        convergence_threshold=settings.DINA_EM_CONVERGENCE_THRESHOLD,
    )
    logger.info(
        "EM 题目参数估计完成: 迭代 %d 次, 收敛=%s, 样本学生 %d 人, 题目 %d 道",
        em_result.iterations,
        em_result.converged,
        len(by_user),
        qmatrix.J,
    )

    # 4. 贝叶斯后验推断该学生 α 向量（先验 = 上一轮 α）
    student_responses = by_user[user_id]
    posterior = await asyncio.to_thread(
        infer_mastery_posterior,
        student_responses,
        qmatrix,
        em_result.slip,
        em_result.guess,
        student_prior,
    )
    alpha_vector = {
        kp_id: round(probability, 6)
        for kp_id, probability in zip(qmatrix.attribute_ids, posterior)
    }

    # 5. 同步更新 user_kp_mastery：仅更新有作答证据的知识点
    active_attrs = sorted(
        {
            attr
            for question_index in student_responses
            for attr in qmatrix.attribute_indices(
                qmatrix.question_ids[question_index]
            )
        }
    )
    active_kp_ids = [qmatrix.attribute_ids[a] for a in active_attrs]
    stats = await asyncio.to_thread(_db_load_kp_statistics, user_id, active_kp_ids)
    kp_updates: Dict[str, dict] = {}
    for attr in active_attrs:
        kp_id = qmatrix.attribute_ids[attr]
        row = stats.get(kp_id, {"questions_done": 0, "correct_count": 0})
        kp_updates[kp_id] = {
            "mastery_probability": round(posterior[attr], 6),
            "questions_done": row["questions_done"],
            "correct_count": row["correct_count"],
        }

    answer_times = [record.created_at for record in student_records if record.created_at]
    answer_time_from = _format_answer_time(min(answer_times)) if answer_times else None
    answer_time_to = _format_answer_time(max(answer_times)) if answer_times else None
    trace = DiagnosisTrace(
        algorithm_version=DINA_ALGORITHM_VERSION,
        parameter_version=DINA_PARAMETER_VERSION,
        answer_count=len(student_records),
        answer_time_from=answer_time_from,
        answer_time_to=answer_time_to,
        repeat_strategy=DINA_REPEAT_STRATEGY,
        converged=em_result.converged,
        iterations=em_result.iterations,
    )

    # 6. 写入诊断会话 + 掌握快照（同一事务）
    # 业务时间戳用服务器本地时间（与 SQL Server GETDATE() 口径一致）
    session_id = _generate_session_id()
    diagnosed_at = get_local_now().replace(microsecond=0)
    await asyncio.to_thread(
        _call_compat_loader,
        _db_save_diagnosis,
        session_id,
        user_id,
        json.dumps(alpha_vector, ensure_ascii=False),
        len(student_records),
        diagnosed_at,
        kp_updates,
        trace,
    )
    logger.info(
        "DINA 诊断完成: user_id=%s, session_id=%s, 用答题 %d 条, "
        "更新时间范围=%s~%s, 策略=%s, 收敛=%s/%d, 更新知识点 %d 个",
        user_id,
        session_id,
        len(student_records),
        answer_time_from,
        answer_time_to,
        DINA_REPEAT_STRATEGY,
        em_result.converged,
        em_result.iterations,
        len(kp_updates),
    )

    return DiagnosisResult(
        alpha_vector=alpha_vector,
        diagnosed_at=diagnosed_at.strftime("%Y-%m-%dT%H:%M:%S"),
        trace=trace,
    )


async def get_latest_diagnosis(user_id: str) -> Optional[DiagnosisResult]:
    """读取当前学生最近一次诊断，供诊断页初始化时展示真实时间。"""
    return await asyncio.to_thread(_db_load_latest_diagnosis, user_id)
