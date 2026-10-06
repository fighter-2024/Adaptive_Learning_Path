"""学员正式取题路由。"""

import logging
from typing import Annotated

import pyodbc
from fastapi import APIRouter, Depends, Query
from neo4j.exceptions import DriverError, Neo4jError

from app.models import ApiResponse, StatusCode
from app.models.auth import UserInfo
from app.models.student_question import StudentQuestionList, StudentQuestionQuery
from app.routers.dependencies import require_student
from app.services.student_question_service import (
    StudentQuestionKnowledgePointNotFoundError,
    list_student_questions,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/questions", response_model=ApiResponse[StudentQuestionList])
async def student_list_questions(
    query: Annotated[StudentQuestionQuery, Query()],
    current_user: UserInfo = Depends(require_student),
):
    """按知识点取学生题目，返回题干、选项和难度，不返回答案或解析。"""
    try:
        return ApiResponse.success(
            data=await list_student_questions(
                knowledge_point_id=query.knowledge_point_id,
                user_id=current_user.user_id,
                count=query.count,
                exclude_done=query.exclude_done,
                question_type=query.type,
            ),
            message="取题成功",
        )
    except StudentQuestionKnowledgePointNotFoundError:
        return ApiResponse.error(
            code=StatusCode.NOT_FOUND,
            message="知识点不存在",
        )
    except (DriverError, Neo4jError) as exc:
        logger.error("学员取题 Neo4j 异常: %s", exc)
        return ApiResponse.error(
            code=StatusCode.NEO4J_ERROR,
            message="图数据库异常，请稍后重试",
        )
    except pyodbc.Error as exc:
        logger.error("学员取题 SQL Server 异常: %s", exc)
        return ApiResponse.error(
            code=StatusCode.DATABASE_ERROR,
            message="数据库异常，请稍后重试",
        )
