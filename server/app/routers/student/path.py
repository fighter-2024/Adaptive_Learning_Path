"""
学员端路由 — 学习路径

严格对照 docs/API契约文档.md「2.4 学习路径」实现：
- GET /path         获取推荐学习路径（目标模式 / 全局模式）
- GET /path/explain 获取路径推荐的 AI 通俗解释（大模型失败自动降级）

Router 只做路由和参数校验，业务逻辑在 learning_path_service。

认证说明：历史只读接口保留可选身份行为；携带有效 student Token 时按该学生
的掌握数据推荐，未登录时提供匿名只读视角。
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from neo4j.exceptions import DriverError, Neo4jError

from app.models import ApiResponse, StatusCode
from app.models.auth import UserInfo
from app.models.learning_path import LearningPathData, PathExplainData
from app.routers.dependencies import get_current_user_optional
from app.services.learning_path_service import (
    KnowledgeGraphCycleError,
    TargetNotFoundError,
    explain_path,
    recommend_path,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/path")


def _error_neo4j(e: Exception) -> ApiResponse:
    """将 Neo4j 异常转换为统一错误响应（不暴露内部堆栈）"""
    logger.error("学员端学习路径 Neo4j 异常: %s", e)
    return ApiResponse.error(
        code=StatusCode.NEO4J_ERROR,
        message="图数据库异常，请稍后重试",
    )


def _error_graph_cycle(e: KnowledgeGraphCycleError) -> ApiResponse:
    """将图谱环路异常转换为统一错误响应（用户可读，不暴露内部细节）"""
    logger.error("学习路径推荐失败，图谱前置关系存在环路: %s", e)
    return ApiResponse.error(
        code=StatusCode.NEO4J_ERROR,
        message="知识图谱前置关系存在环路，请联系管理员修复",
    )


@router.get("", response_model=ApiResponse[LearningPathData])
async def get_learning_path(
    target_kp_id: Optional[str] = Query(
        None, max_length=32, description="目标知识点 ID，不传则推荐全局下一步"
    ),
    count: int = Query(5, ge=1, le=50, description="推荐步数，默认 5"),
    current_user: Optional[UserInfo] = Depends(get_current_user_optional),
):
    """获取推荐学习路径（对照契约 GET /api/student/path）

    目标模式（传 target_kp_id）：推荐通往目标知识点的学习序列；
    全局模式（不传）：按多指标贪心推荐全局下一步序列。
    序列经拓扑排序 + 贪心选择，前置关系不被违反，每步含中文 reason；
    已掌握（≥0.8）的知识点不进入推荐。

    Args:
        target_kp_id: 目标知识点 ID；不传则全局推荐
        count: 推荐步数（1-50，默认 5）
        current_user: 可选身份解析；未登录时按匿名只读视角处理

    Returns:
        ApiResponse[LearningPathData]: data.target（全局模式为 null）与
        data.steps（每步含 order/knowledge_point/reason/difficulty/
        estimated_time/mastery_probability）
    """
    user_id = current_user.user_id if current_user else None
    try:
        data = await recommend_path(user_id, target_kp_id, count)
        return ApiResponse.success(data=data, message="查询成功")
    except TargetNotFoundError:
        return ApiResponse.error(
            code=StatusCode.NOT_FOUND, message="目标知识点不存在"
        )
    except KnowledgeGraphCycleError as e:
        return _error_graph_cycle(e)
    except (DriverError, Neo4jError) as e:
        return _error_neo4j(e)


@router.get("/explain", response_model=ApiResponse[PathExplainData])
async def get_learning_path_explain(
    target_kp_id: Optional[str] = Query(
        None, max_length=32, description="目标知识点 ID，不传则解释全局推荐路径"
    ),
    count: int = Query(5, ge=1, le=50, description="解释的路径步数，默认 5"),
    current_user: Optional[UserInfo] = Depends(get_current_user_optional),
):
    """获取路径推荐的 AI 通俗解释（对照契约 GET /api/student/path/explain）

    先按 /path 同规则生成推荐路径，再调用大模型生成通俗解释；
    大模型未配置/超时/失败时降级为规则拼装的解释（总则第八章），
    接口始终返回可用的 explanation，不阻塞业务流程。

    Args:
        target_kp_id: 目标知识点 ID；不传则解释全局推荐路径
        count: 解释的路径步数（1-50，默认 5）
        current_user: 可选身份解析；未登录时按匿名只读视角处理

    Returns:
        ApiResponse[PathExplainData]: data.explanation 为解释文本
    """
    user_id = current_user.user_id if current_user else None
    try:
        explanation = await explain_path(user_id, target_kp_id, count)
        return ApiResponse.success(
            data=PathExplainData(explanation=explanation), message="查询成功"
        )
    except TargetNotFoundError:
        return ApiResponse.error(
            code=StatusCode.NOT_FOUND, message="目标知识点不存在"
        )
    except KnowledgeGraphCycleError as e:
        return _error_graph_cycle(e)
    except (DriverError, Neo4jError) as e:
        return _error_neo4j(e)
