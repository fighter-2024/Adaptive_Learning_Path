"""AI 路由的统一错误转换。"""
import logging
from typing import Any, Awaitable
import pyodbc
from neo4j.exceptions import DriverError, Neo4jError
from app.models import ApiResponse, StatusCode
from app.services.ai_service import KnowledgeNotFoundError
from app.services.weekly_report_service import InvalidWeekError

logger = logging.getLogger(__name__)


async def respond(operation: Awaitable[Any]) -> ApiResponse:
    """数据库故障不可伪装为模型降级成功，不记录异常原文。"""
    try:
        return ApiResponse.success(data=await operation)
    except KnowledgeNotFoundError:
        return ApiResponse.error(code=StatusCode.NOT_FOUND, message='知识点不存在')
    except InvalidWeekError:
        return ApiResponse.error(code=StatusCode.BAD_REQUEST, message='请选择非未来的周一日期')
    except (pyodbc.Error, ValueError, TypeError):
        logger.error('AI data outcome=sql_or_data_error')
        return ApiResponse.error(code=StatusCode.DATABASE_ERROR, message='数据库或学习数据异常，请稍后重试')
    except (DriverError, Neo4jError):
        logger.error('AI data outcome=graph_error')
        return ApiResponse.error(code=StatusCode.NEO4J_ERROR, message='图数据库异常，请稍后重试')
