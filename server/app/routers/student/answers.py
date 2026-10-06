"""
学员端路由 — 答题提交

严格对照 docs/改进计划与任务卡/API契约文档-v2.md「3.3 答题」实现：
- POST /submit-answer  提交单题答案（判题 + 掌握概率更新 + 写入答题记录）
- POST /submit-batch   批量提交（逐题判题，返回每题结果 + 汇总统计）

Router 只做路由和参数校验，业务逻辑在 service 层
（app/services/answer_submission_service.py）。

认证说明：答题是写操作（写 answer_records / user_kp_mastery），
无法像知识点读接口那样匿名降级，故本模块强制学生身份
（Depends(require_student)）：未携带 Token 返回 401，非学生角色返回 403。
这与 routers/student/__init__.py 的「全局开启 require_student」占位方案
方向一致，后续全局开启时无需改动本模块。

错误映射：
- 题目不存在/已下线      → 40400「题目不存在」
- 数据库异常             → 50001「数据库异常，请稍后重试」（不暴露堆栈）
- 批量提交中单题不存在   → 记入该题 error 字段，不阻塞其他题
- 每次有效提交都是一次 attempt；重做允许新增记录，页面侧通过提交中禁用避免重复点击
"""

import logging

import pyodbc
from fastapi import APIRouter, Depends

from app.models import ApiResponse, StatusCode
from app.models.answer_submission import (
    AnswerSubmitRequest,
    SubmitAnswerResult,
    SubmitBatchRequest,
    SubmitBatchResult,
)
from app.models.auth import UserInfo
from app.routers.dependencies import require_student
from app.services.answer_submission_service import (
    QuestionNotFoundError,
    submit_answer,
    submit_batch,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _error_sqlserver(e: Exception) -> ApiResponse:
    """将 SQL Server 异常转换为统一错误响应（不暴露内部堆栈）"""
    logger.error("学员端答题 SQL Server 异常: %s", e)
    return ApiResponse.error(
        code=StatusCode.DATABASE_ERROR,
        message="数据库异常，请稍后重试",
    )


@router.post("/submit-answer", response_model=ApiResponse[SubmitAnswerResult])
async def student_submit_answer(
    body: AnswerSubmitRequest,
    current_user: UserInfo = Depends(require_student),
):
    """提交单题答案

    流程：按题型判题 → 更新题目关联知识点的掌握概率（user_kp_mastery）
    → 写入答题记录（answer_records），三者同一事务。

    Args:
        body: question_id / student_answer / time_spent
        current_user: 当前学生身份（JWT 依赖注入）

    Returns:
        ApiResponse[SubmitAnswerResult]: correct / correct_answer /
            explanation / mastery_change（知识点掌握概率变化）
    """
    try:
        result = await submit_answer(
            user_id=current_user.user_id,
            question_id=body.question_id,
            student_answer=body.student_answer,
            time_spent=body.time_spent,
        )
        return ApiResponse.success(data=result, message="判题完成")
    except QuestionNotFoundError:
        return ApiResponse.error(
            code=StatusCode.NOT_FOUND,
            message="题目不存在",
        )
    except pyodbc.Error as e:
        return _error_sqlserver(e)


@router.post("/submit-batch", response_model=ApiResponse[SubmitBatchResult])
async def student_submit_batch(
    body: SubmitBatchRequest,
    current_user: UserInfo = Depends(require_student),
):
    """批量提交答案

    逐题判题（顺序与入参一致）；题目不存在（含已下线）的项记入该题
    error 字段并跳过，不阻塞其他题；全部成功项在同一事务中写入
    answer_records 与 user_kp_mastery。

    Args:
        body: answers 答案数组（每项结构同 submit-answer）
        current_user: 当前学生身份（JWT 依赖注入）

    Returns:
        ApiResponse[SubmitBatchResult]: results（每题判题结果汇总）+
            summary（total/correct_count/wrong_count/fail_count/correct_rate）
    """
    try:
        result = await submit_batch(
            user_id=current_user.user_id,
            answers=body.answers,
        )
        return ApiResponse.success(data=result, message="批量判题完成")
    except pyodbc.Error as e:
        return _error_sqlserver(e)
