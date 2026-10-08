"""管理端学生列表与学生详情路由。"""

import logging
from typing import Optional

import pyodbc
from fastapi import APIRouter, Path, Query
from neo4j.exceptions import DriverError, Neo4jError

from app.models import ApiResponse, PaginatedData, StatusCode
from app.models.admin_dashboard import StudentDetail, StudentListItem
from app.services.admin_dashboard_service import get_student_detail, list_students
from app.services.learning_path_service import KnowledgeGraphCycleError, TargetNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/students")


@router.get("", response_model=ApiResponse[PaginatedData[StudentListItem]])
async def admin_list_students(
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    keyword: Optional[str] = Query(default=None, max_length=100, description="搜索学生 ID、账号或姓名"),
):
    """分页查询学生，并返回最近活跃时间与学习摘要。"""
    try:
        items, total = await list_students(
            page=page,
            page_size=page_size,
            keyword=keyword.strip() if keyword else None,
        )
        return ApiResponse.success(
            data=PaginatedData(list=items, total=total, page=page, page_size=page_size),
            message="查询成功",
        )
    except pyodbc.Error as exc:
        logger.error("管理端学生列表 SQL Server 异常: %s", exc)
        return ApiResponse.error(StatusCode.DATABASE_ERROR, "数据库异常，请稍后重试")
    except (DriverError, Neo4jError) as exc:
        logger.error("管理端学生列表 Neo4j 异常: %s", exc)
        return ApiResponse.error(StatusCode.NEO4J_ERROR, "图数据库异常，请稍后重试")


@router.get("/{student_id}", response_model=ApiResponse[StudentDetail])
async def admin_get_student(
    student_id: str = Path(..., min_length=1, max_length=32, description="学生业务 ID"),
):
    """读取目标学生的基本信息、掌握度、诊断、答题记录和推荐路径。"""
    try:
        data = await get_student_detail(student_id)
        if data is None:
            return ApiResponse.error(StatusCode.NOT_FOUND, "学生不存在")
        return ApiResponse.success(data=data, message="查询成功")
    except TargetNotFoundError as exc:
        logger.warning("学生详情推荐路径目标异常: %s", exc)
        return ApiResponse.error(StatusCode.NEO4J_ERROR, "知识图谱数据异常，请联系管理员")
    except KnowledgeGraphCycleError as exc:
        logger.error("学生详情推荐路径检测到图谱环路: %s", exc)
        return ApiResponse.error(StatusCode.NEO4J_ERROR, "知识图谱前置关系存在环路，请联系管理员修复")
    except pyodbc.Error as exc:
        logger.error("管理端学生详情 SQL Server 异常: %s", exc)
        return ApiResponse.error(StatusCode.DATABASE_ERROR, "数据库异常，请稍后重试")
    except (DriverError, Neo4jError) as exc:
        logger.error("管理端学生详情 Neo4j 异常: %s", exc)
        return ApiResponse.error(StatusCode.NEO4J_ERROR, "图数据库异常，请稍后重试")
