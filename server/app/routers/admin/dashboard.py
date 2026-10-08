"""管理端仪表盘路由。"""

import logging

import pyodbc
from fastapi import APIRouter
from neo4j.exceptions import DriverError, Neo4jError

from app.models import ApiResponse, DashboardSummary, StatusCode
from app.services.admin_dashboard_service import get_dashboard_summary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard")


@router.get("/summary", response_model=ApiResponse[DashboardSummary])
async def admin_dashboard_summary():
    """读取学生、题目、知识点、本周活跃和最近诊断的真实统计。"""
    try:
        data = await get_dashboard_summary()
        return ApiResponse.success(data=data, message="查询成功")
    except pyodbc.Error as exc:
        logger.error("管理端仪表盘 SQL Server 异常: %s", exc)
        return ApiResponse.error(StatusCode.DATABASE_ERROR, "数据库异常，请稍后重试")
    except (DriverError, Neo4jError) as exc:
        logger.error("管理端仪表盘 Neo4j 异常: %s", exc)
        return ApiResponse.error(StatusCode.NEO4J_ERROR, "图数据库异常，请稍后重试")
