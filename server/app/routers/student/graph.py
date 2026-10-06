"""学生端图谱查询路由。"""

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Path, Query
from neo4j.exceptions import DriverError, Neo4jError

from app.models import ApiResponse, StatusCode
from app.models.auth import UserInfo
from app.models.graph import GraphData, GraphView
from app.routers.dependencies import require_student
from app.services.graph_service import (
    GraphFocusNotFoundError,
    GraphNeo4jError,
    GraphSqlServerError,
    get_student_graph,
    get_student_neighbors,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/graph")


def _neo4j_error(exc: Exception) -> ApiResponse:
    """统一返回图数据库错误，不暴露内部异常。"""
    logger.error("学生图谱 Neo4j 异常: %s", exc)
    return ApiResponse.error(StatusCode.NEO4J_ERROR, "图数据库异常，请稍后重试")


def _sql_error(exc: Exception) -> ApiResponse:
    """统一返回掌握度数据库错误，不伪装成空图。"""
    logger.error("学生图谱 SQL Server 异常: %s", exc)
    return ApiResponse.error(StatusCode.DATABASE_ERROR, "数据库异常，请稍后重试")


@router.get("", response_model=ApiResponse[GraphData])
async def student_graph(
    view: GraphView = Query("personalized"),
    focus_id: Optional[str] = Query(None, max_length=32),
    depth: int = Query(2, ge=0, le=3),
    max_nodes: int = Query(80, ge=1, le=500),
    include_mastered: bool = Query(True),
    current_user: UserInfo = Depends(require_student),
):
    """获取 tree/network/personalized 学生图谱。"""
    try:
        data = await get_student_graph(
            user_id=current_user.user_id,
            view=view,
            focus_id=focus_id,
            depth=depth,
            max_nodes=max_nodes,
            include_mastered=include_mastered,
        )
        return ApiResponse.success(data=data, message="查询成功")
    except GraphFocusNotFoundError:
        return ApiResponse.error(StatusCode.NOT_FOUND, "聚焦知识点不存在")
    except GraphSqlServerError as exc:
        return _sql_error(exc)
    except (GraphNeo4jError, DriverError, Neo4jError) as exc:
        return _neo4j_error(exc)


@router.get("/{id}/neighbors", response_model=ApiResponse[GraphData])
async def student_graph_neighbors(
    kp_id: str = Path(..., alias="id", max_length=32),
    direction: Literal["both", "incoming", "outgoing"] = Query("both"),
    depth: int = Query(1, ge=1, le=2),
    max_nodes: int = Query(30, ge=1, le=100),
    current_user: UserInfo = Depends(require_student),
):
    """获取焦点知识点的局部关系网，避免按邻居逐条查询。"""
    try:
        data = await get_student_neighbors(
            user_id=current_user.user_id,
            focus_id=kp_id,
            direction=direction,
            depth=depth,
            max_nodes=max_nodes,
        )
        return ApiResponse.success(data=data, message="查询成功")
    except GraphFocusNotFoundError:
        return ApiResponse.error(StatusCode.NOT_FOUND, "知识点不存在")
    except GraphSqlServerError as exc:
        return _sql_error(exc)
    except (GraphNeo4jError, DriverError, Neo4jError) as exc:
        return _neo4j_error(exc)
