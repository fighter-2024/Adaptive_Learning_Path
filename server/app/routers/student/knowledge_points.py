"""
学员端路由 — 知识点（学习模块）

严格对照 docs/API契约文档.md「2.1 学习」实现：
- GET /knowledge-points       学员视角知识点列表（含掌握概率与掌握状态）
- GET /knowledge-points/{id}  知识点详情（前置知识点掌握状态 + 关联题目列表）

status 枚举：mastered(≥0.8) / learning(0.4-0.8) / weak(<0.4) / not_started(无数据)。

Router 只做路由和参数校验，业务逻辑在 service 层。

认证说明：历史只读接口保留可选身份行为，兼容尚未登录的只读浏览；携带有效
student Token 时使用对应学生的掌握数据，写操作和图谱接口仍强制鉴权。
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Path
from neo4j.exceptions import DriverError, Neo4jError

from app.models import ApiResponse, StatusCode
from app.models.auth import UserInfo
from app.models.student_knowledge_point import (
    StudentKnowledgePointDetail,
    StudentKnowledgePointList,
)
from app.routers.dependencies import get_current_user_optional
from app.services.student_knowledge_point_service import (
    get_student_knowledge_point,
    list_student_knowledge_points,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge-points")


def _error_neo4j(e: Exception) -> ApiResponse:
    """将 Neo4j 异常转换为统一错误响应（不暴露内部堆栈）"""
    logger.error("学员端知识点 Neo4j 异常: %s", e)
    return ApiResponse.error(
        code=StatusCode.NEO4J_ERROR,
        message="图数据库异常，请稍后重试",
    )


@router.get("", response_model=ApiResponse[StudentKnowledgePointList])
async def student_list_knowledge_points(
    current_user: Optional[UserInfo] = Depends(get_current_user_optional),
):
    """获取学员视角知识点列表（含每个知识点的掌握概率与掌握状态）

    数据来源：知识点基础信息（Neo4j）+ 学员掌握快照 user_kp_mastery
    （SQL Server，AI开发总则第六条职责划分）。
    status 由 mastery_probability 按契约阈值计算：
    mastered(≥0.8) / learning(0.4-0.8) / weak(<0.4) / not_started(无数据)。

    Args:
        current_user: 可选身份解析；未登录时返回匿名只读视角

    Returns:
        ApiResponse[StudentKnowledgePointList]: data.list 为知识点列表
        （契约规定该接口为非分页结构，无 total/page/page_size）
    """
    user_id = current_user.user_id if current_user else None
    try:
        items = await list_student_knowledge_points(user_id)
        return ApiResponse.success(
            data=StudentKnowledgePointList(list=items),
            message="查询成功",
        )
    except (DriverError, Neo4jError) as e:
        return _error_neo4j(e)


@router.get("/{id}", response_model=ApiResponse[StudentKnowledgePointDetail])
async def student_get_knowledge_point(
    kp_id: str = Path(..., alias="id", max_length=32, description="知识点 ID"),
    current_user: Optional[UserInfo] = Depends(get_current_user_optional),
):
    """获取知识点详情（含前置知识点掌握状态 + 关联题目列表）

    前置知识点 mastered = 该学员对应掌握概率 ≥ 0.8；
    关联题目 done = 该学员在 answer_records 中有过作答记录。
    学员视角不返回题目答案与解析（避免泄题）。

    Args:
        kp_id: 知识点 ID
        current_user: 可选身份解析；未登录时返回匿名只读视角

    Returns:
        ApiResponse[StudentKnowledgePointDetail]: 知识点详情
    """
    user_id = current_user.user_id if current_user else None
    try:
        detail = await get_student_knowledge_point(kp_id, user_id)
        if detail is None:
            return ApiResponse.error(
                code=StatusCode.NOT_FOUND,
                message="知识点不存在",
            )
        return ApiResponse.success(data=detail, message="查询成功")
    except (DriverError, Neo4jError) as e:
        return _error_neo4j(e)
