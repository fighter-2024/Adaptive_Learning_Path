"""
管理后台路由 — 知识点管理

严格对照 docs/API契约文档.md「1.1 知识点管理」实现：
- GET    /knowledge-points               分页查询 + 按章节筛选 + 按名称搜索
- GET    /knowledge-points/{id}          单个详情（含前置/后继知识点）
- POST   /knowledge-points               新增知识点
- PUT    /knowledge-points/{id}          编辑知识点
- DELETE /knowledge-points/{id}          删除（有依赖则拒绝）
- POST   /knowledge-points/{id}/prerequisites  全量替换前置关系

Router 只做路由和参数校验，业务逻辑在 service 层。
"""

import logging
from typing import Optional

from fastapi import APIRouter, Path, Query
from neo4j.exceptions import DriverError, Neo4jError

from app.models import ApiResponse, PaginatedData, StatusCode
from app.models.knowledge_point import (
    KnowledgePointCreateRequest,
    KnowledgePointDetail,
    KnowledgePointItem,
    PrerequisitesUpdateRequest,
)
from app.services.knowledge_point_service import (
    ChapterNotFoundError,
    KnowledgePointDependencyError,
    KnowledgePointNotFoundError,
    PrerequisiteValidationError,
    create_knowledge_point,
    delete_knowledge_point,
    get_knowledge_point,
    list_knowledge_points,
    replace_prerequisites,
    update_knowledge_point,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge-points")


def _error_neo4j(e: Exception) -> ApiResponse:
    """将 Neo4j 异常转换为统一错误响应（不暴露内部堆栈）"""
    logger.error("知识点管理 Neo4j 异常: %s", e)
    return ApiResponse.error(
        code=StatusCode.NEO4J_ERROR,
        message="图数据库异常，请稍后重试",
    )


@router.get("", response_model=ApiResponse[PaginatedData[KnowledgePointItem]])
async def admin_list_knowledge_points(
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数，最大 100"),
    chapter_id: Optional[str] = Query(default=None, max_length=32, description="按章节筛选"),
    keyword: Optional[str] = Query(default=None, max_length=100, description="按名称模糊搜索"),
):
    """查询知识点列表（分页 + 筛选）

    支持按章节（chapter_id）筛选、按名称（keyword）模糊搜索。

    Args:
        page: 页码，默认 1
        page_size: 每页条数，默认 20，最大 100
        chapter_id: 章节 ID，可选
        keyword: 名称关键词，可选

    Returns:
        ApiResponse[PaginatedData[KnowledgePointItem]]: 分页列表
    """
    # 空字符串视为未传筛选条件
    if keyword is not None:
        keyword = keyword.strip() or None

    try:
        items, total = await list_knowledge_points(
            page=page,
            page_size=page_size,
            chapter_id=chapter_id,
            keyword=keyword,
        )
        return ApiResponse.success(
            data=PaginatedData(
                list=items,
                total=total,
                page=page,
                page_size=page_size,
            ),
            message="查询成功",
        )
    except (DriverError, Neo4jError) as e:
        return _error_neo4j(e)


@router.get("/{id}", response_model=ApiResponse[KnowledgePointDetail])
async def admin_get_knowledge_point(
    kp_id: str = Path(..., alias="id", max_length=32, description="知识点 ID"),
):
    """查询单个知识点详情（含前置/后继知识点）

    Args:
        kp_id: 知识点 ID

    Returns:
        ApiResponse[KnowledgePointDetail]: 详情，含 prerequisites/dependents
    """
    try:
        detail = await get_knowledge_point(kp_id)
        if detail is None:
            return ApiResponse.error(
                code=StatusCode.NOT_FOUND,
                message="知识点不存在",
            )
        return ApiResponse.success(data=detail, message="查询成功")
    except (DriverError, Neo4jError) as e:
        return _error_neo4j(e)


@router.post("", response_model=ApiResponse[KnowledgePointItem])
async def admin_create_knowledge_point(body: KnowledgePointCreateRequest):
    """新增知识点

    Args:
        body: 知识点信息，含 name/description/chapter_id/difficulty/estimated_time

    Returns:
        ApiResponse[KnowledgePointItem]: 创建后的知识点对象（含 id）
    """
    try:
        item = await create_knowledge_point(
            name=body.name,
            description=body.description,
            chapter_id=body.chapter_id,
            difficulty=body.difficulty,
            estimated_time=body.estimated_time,
            prerequisite_ids=body.prerequisite_ids,
        )
        return ApiResponse.success(data=item, message="创建成功")
    except ChapterNotFoundError as e:
        return ApiResponse.error(code=StatusCode.BAD_REQUEST, message=str(e))
    except PrerequisiteValidationError as e:
        return ApiResponse.error(code=StatusCode.GRAPH_QUERY_INVALID, message=str(e))
    except (DriverError, Neo4jError) as e:
        return _error_neo4j(e)


@router.put("/{id}", response_model=ApiResponse[KnowledgePointItem])
async def admin_update_knowledge_point(
    body: KnowledgePointCreateRequest,
    kp_id: str = Path(..., alias="id", max_length=32, description="知识点 ID"),
):
    """编辑知识点

    Args:
        body: 知识点信息（请求体同 POST）
        kp_id: 知识点 ID

    Returns:
        ApiResponse[KnowledgePointItem]: 更新后的知识点对象
    """
    try:
        item = await update_knowledge_point(
            kp_id=kp_id,
            name=body.name,
            description=body.description,
            chapter_id=body.chapter_id,
            difficulty=body.difficulty,
            estimated_time=body.estimated_time,
            prerequisite_ids=body.prerequisite_ids,
        )
        if item is None:
            return ApiResponse.error(
                code=StatusCode.NOT_FOUND,
                message="知识点不存在",
            )
        return ApiResponse.success(data=item, message="更新成功")
    except ChapterNotFoundError as e:
        return ApiResponse.error(code=StatusCode.BAD_REQUEST, message=str(e))
    except PrerequisiteValidationError as e:
        return ApiResponse.error(code=StatusCode.GRAPH_QUERY_INVALID, message=str(e))
    except (DriverError, Neo4jError) as e:
        return _error_neo4j(e)


@router.delete("/{id}", response_model=ApiResponse[None])
async def admin_delete_knowledge_point(
    kp_id: str = Path(..., alias="id", max_length=32, description="知识点 ID"),
):
    """删除知识点

    删除前检查是否有其他知识点依赖它，有依赖则返回 code=40001
    拒绝删除（与 API 契约一致）。

    Args:
        kp_id: 知识点 ID

    Returns:
        ApiResponse: 成功时 data 为 null，message 为「删除成功」
    """
    try:
        await delete_knowledge_point(kp_id)
        return ApiResponse.success(data=None, message="删除成功")
    except KnowledgePointNotFoundError:
        return ApiResponse.error(
            code=StatusCode.NOT_FOUND,
            message="知识点不存在",
        )
    except KnowledgePointDependencyError as e:
        # 契约 1.1 规定：被依赖无法删除时返回 code 40001
        return ApiResponse.error(
            code=StatusCode.KNOWLEDGE_POINT_HAS_DEPENDENTS,
            message=str(e),
        )
    except (DriverError, Neo4jError) as e:
        return _error_neo4j(e)


@router.post("/{id}/prerequisites", response_model=ApiResponse[KnowledgePointDetail])
async def admin_replace_prerequisites(
    body: PrerequisitesUpdateRequest,
    kp_id: str = Path(..., alias="id", max_length=32, description="知识点 ID"),
):
    """全量替换前置依赖

    传什么就是什么（不追加），空列表表示清空所有前置。
    替换前校验：知识点存在、前置知识点存在、不含自身、无环。

    Args:
        body: 新前置知识点 ID 列表
        kp_id: 知识点 ID

    Returns:
        ApiResponse[KnowledgePointDetail]: 替换后的知识点详情
    """
    try:
        detail = await replace_prerequisites(kp_id, body.prerequisite_ids)
        return ApiResponse.success(data=detail, message="前置依赖更新成功")
    except KnowledgePointNotFoundError:
        return ApiResponse.error(
            code=StatusCode.NOT_FOUND,
            message="知识点不存在",
        )
    except PrerequisiteValidationError as e:
        return ApiResponse.error(
            code=StatusCode.GRAPH_QUERY_INVALID,
            message=str(e),
        )
    except (DriverError, Neo4jError) as e:
        return _error_neo4j(e)
