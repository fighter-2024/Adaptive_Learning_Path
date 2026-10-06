"""
学员端路由 — DINA 认知诊断

严格对照 docs/API契约文档.md「2.3 诊断」实现：
- POST /diagnosis  触发 DINA 诊断（根据答题记录重新推断 α 向量）

Router 只做路由和参数校验，业务逻辑在 service 层
（app/services/diagnosis_service.py）。

认证说明：诊断是写操作（写 diagnosis_sessions / user_kp_mastery），
强制学生身份（Depends(require_student)），与答题模块一致。

错误映射：
- 答题记录不足（含 Q 矩阵无数据）→ 40002「答题记录不足，无法进行认知诊断」
- 数据库异常                 → 50001「数据库异常，请稍后重试」（不暴露堆栈）
"""

import logging

import pyodbc
from fastapi import APIRouter, Depends

from app.models import ApiResponse, StatusCode
from app.models.auth import UserInfo
from app.models.diagnosis import DiagnosisResult
from app.routers.dependencies import require_student
from app.services.diagnosis_service import (
    InsufficientAnswerError,
    diagnose_student,
    get_latest_diagnosis,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/diagnosis",
    response_model=ApiResponse[dict],
)
async def student_diagnosis(
    current_user: UserInfo = Depends(require_student),
):
    """触发 DINA 认知诊断

    以当前学生按 latest_attempt 聚合后的答题记录运行 EM 估计题目参数
    （失误率 s / 猜测率 g），再以该学生上一轮掌握向量为先验做贝叶斯
    后验推断 α；结果写入 diagnosis_sessions 并同步更新 user_kp_mastery。

    Args:
        current_user: 当前学生身份（JWT 依赖注入）

    Returns:
        ApiResponse[DiagnosisResult]: alpha_vector + diagnosed_at
    """
    try:
        result = await diagnose_student(current_user.user_id)
        # 只省略历史兼容结果中的空 trace；错误响应仍保留 data:null。
        return ApiResponse.success(
            data=result.model_dump(exclude_none=True), message="诊断完成"
        )
    except InsufficientAnswerError:
        return ApiResponse.error(
            code=StatusCode.DIAGNOSIS_INSUFFICIENT_DATA,
            message="答题记录不足，无法进行认知诊断",
        )
    except pyodbc.Error as e:
        logger.error("学员端诊断 SQL Server 异常: %s", e)
        return ApiResponse.error(
            code=StatusCode.DATABASE_ERROR,
            message="数据库异常，请稍后重试",
        )
    except ValueError as e:
        logger.error("DINA 参数或数据校验失败: %s", e)
        return ApiResponse.error(
            code=StatusCode.DATABASE_ERROR,
            message="诊断参数异常，请稍后重试",
        )


@router.get(
    "/diagnosis",
    response_model=ApiResponse[dict],
)
async def student_latest_diagnosis(
    current_user: UserInfo = Depends(require_student),
):
    """读取当前学生最近一次诊断，供诊断页恢复真实状态。"""
    try:
        result = await get_latest_diagnosis(current_user.user_id)
        data = result.model_dump(exclude_none=True) if result else None
        return ApiResponse.success(data=data, message="查询成功")
    except pyodbc.Error as e:
        logger.error("读取最近诊断 SQL Server 异常: %s", e)
        return ApiResponse.error(
            code=StatusCode.DATABASE_ERROR,
            message="数据库异常，请稍后重试",
        )
