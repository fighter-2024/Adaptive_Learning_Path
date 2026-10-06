"""管理端图谱查询路由。"""

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Query
from neo4j.exceptions import DriverError, Neo4jError
from pydantic import BaseModel, Field

from app.models import ApiResponse, StatusCode
from app.models.graph import GraphData
from app.services.graph_service import (
    GraphFocusNotFoundError,
    GraphNeo4jError,
    get_admin_graph,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/graph")


class AdminGraphQuery(BaseModel):
    """管理端图谱查询参数，统一由 Pydantic 校验。"""

    chapter_id: Optional[str] = Field(default=None, max_length=32)
    keyword: Optional[str] = Field(default=None, max_length=100)
    focus_id: Optional[str] = Field(default=None, max_length=32)
    depth: int = Field(default=2, ge=0, le=3)
    max_nodes: int = Field(default=200, ge=1, le=500)


@router.get("", response_model=ApiResponse[GraphData])
async def admin_graph(
    query: Annotated[AdminGraphQuery, Query()],
):
    """获取管理端图谱，学生字段保持为 null。"""
    try:
        data = await get_admin_graph(
            chapter_id=query.chapter_id,
            keyword=query.keyword.strip() if query.keyword else None,
            focus_id=query.focus_id,
            depth=query.depth,
            max_nodes=query.max_nodes,
        )
        return ApiResponse.success(data=data, message="查询成功")
    except GraphFocusNotFoundError:
        return ApiResponse.error(StatusCode.NOT_FOUND, "聚焦知识点不存在")
    except (GraphNeo4jError, DriverError, Neo4jError) as exc:
        logger.error("管理端图谱 Neo4j 异常: %s", exc)
        return ApiResponse.error(StatusCode.NEO4J_ERROR, "图数据库异常，请稍后重试")
