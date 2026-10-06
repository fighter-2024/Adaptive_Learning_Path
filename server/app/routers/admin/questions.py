"""
管理后台路由 — 题库管理

严格对照 docs/API契约文档.md「1.2 题库管理」实现：
- GET    /questions                分页查询 + 按知识点/题型/难度/关键词筛选
- GET    /questions/{id}           单个详情（含选项和解析）
- POST   /questions                新增题目（含 Q矩阵关联写入 q_matrix 表）
- PUT    /questions/{id}           编辑题目（同步更新 Q矩阵）
- DELETE /questions/{id}           删除题目（同步删除 Q矩阵关联）
- POST   /questions/batch-import   批量导入，返回成功/失败统计

Router 只做路由和参数校验，业务逻辑在 service 层。
"""

import logging
from typing import Annotated

import pyodbc
from fastapi import APIRouter, Path, Query
from neo4j.exceptions import DriverError, Neo4jError

from app.models import ApiResponse, PaginatedData, StatusCode
from app.models.question import (
    QuestionBatchImportRequest,
    QuestionBatchImportResult,
    QuestionCreateRequest,
    QuestionDetail,
    QuestionListItem,
    QuestionListQuery,
)
from app.services.question_service import (
    KnowledgePointMissingError,
    QuestionNotFoundError,
    batch_import_questions,
    create_question,
    delete_question,
    get_question,
    list_questions,
    update_question,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/questions")


def _error_sqlserver(e: Exception) -> ApiResponse:
    """将 SQL Server 异常转换为统一错误响应（不暴露内部堆栈）"""
    logger.error("题库管理 SQL Server 异常: %s", e)
    return ApiResponse.error(
        code=StatusCode.DATABASE_ERROR,
        message="数据库异常，请稍后重试",
    )


def _error_neo4j(e: Exception) -> ApiResponse:
    """将 Neo4j 异常转换为统一错误响应（不暴露内部堆栈）"""
    logger.error("题库管理 Neo4j 异常: %s", e)
    return ApiResponse.error(
        code=StatusCode.NEO4J_ERROR,
        message="图数据库异常，请稍后重试",
    )


@router.get("", response_model=ApiResponse[PaginatedData[QuestionListItem]])
async def admin_list_questions(
    query: Annotated[QuestionListQuery, Query()],
):
    """查询题目列表（分页 + 筛选）

    查询参数全部通过 Pydantic 模型 QuestionListQuery 校验（含难度区间
    交叉校验：difficulty_min 不能大于 difficulty_max）。

    Args:
        query: 分页 + 筛选参数（page/page_size/knowledge_point_id/type/
            difficulty_min/difficulty_max/keyword）

    Returns:
        ApiResponse[PaginatedData[QuestionListItem]]: 分页列表
    """
    # 空字符串视为未传筛选条件
    keyword = query.keyword.strip() if query.keyword else None

    try:
        items, total = await list_questions(
            page=query.page,
            page_size=query.page_size,
            knowledge_point_id=query.knowledge_point_id,
            question_type=query.type,
            difficulty_min=query.difficulty_min,
            difficulty_max=query.difficulty_max,
            keyword=keyword,
        )
        return ApiResponse.success(
            data=PaginatedData(
                list=items,
                total=total,
                page=query.page,
                page_size=query.page_size,
            ),
            message="查询成功",
        )
    except pyodbc.Error as e:
        return _error_sqlserver(e)


@router.post("/batch-import", response_model=ApiResponse[QuestionBatchImportResult])
async def admin_batch_import_questions(body: QuestionBatchImportRequest):
    """批量导入题目，返回成功/失败统计

    逐行独立校验与写入：单行失败记入 errors（含行号和原因），
    不影响其他行导入。整体请求返回 code=0，结果看 data 统计。

    Args:
        body: questions 题目对象数组（结构同 POST 单个）

    Returns:
        ApiResponse[QuestionBatchImportResult]: success_count/fail_count/errors
    """
    try:
        result = await batch_import_questions(body.questions)
        return ApiResponse.success(data=result, message="批量导入完成")
    except (DriverError, Neo4jError) as e:
        return _error_neo4j(e)


@router.get("/{id}", response_model=ApiResponse[QuestionDetail])
async def admin_get_question(
    question_id: str = Path(..., alias="id", max_length=32, description="题目 ID"),
):
    """查询单个题目详情（含选项和解析）

    Args:
        question_id: 题目 ID

    Returns:
        ApiResponse[QuestionDetail]: 题目详情
    """
    try:
        detail = await get_question(question_id)
        if detail is None:
            return ApiResponse.error(
                code=StatusCode.NOT_FOUND,
                message="题目不存在",
            )
        return ApiResponse.success(data=detail, message="查询成功")
    except pyodbc.Error as e:
        return _error_sqlserver(e)


@router.post("", response_model=ApiResponse[QuestionDetail])
async def admin_create_question(body: QuestionCreateRequest):
    """新增题目（含 Q矩阵关联写入 q_matrix 表）

    Args:
        body: 题目信息（题干/题型/难度/选项/答案/解析/关联知识点）

    Returns:
        ApiResponse[QuestionDetail]: 创建后的题目（含 id）
    """
    try:
        detail = await create_question(
            content=body.content,
            question_type=body.type,
            difficulty=body.difficulty,
            options=body.options or [],
            answer=body.answer,
            explanation=body.explanation,
            kp_ids=body.knowledge_point_ids,
        )
        return ApiResponse.success(data=detail, message="创建成功")
    except KnowledgePointMissingError as e:
        return ApiResponse.error(code=StatusCode.BAD_REQUEST, message=str(e))
    except pyodbc.Error as e:
        return _error_sqlserver(e)
    except (DriverError, Neo4jError) as e:
        return _error_neo4j(e)


@router.put("/{id}", response_model=ApiResponse[QuestionDetail])
async def admin_update_question(
    body: QuestionCreateRequest,
    question_id: str = Path(..., alias="id", max_length=32, description="题目 ID"),
):
    """编辑题目（同步更新 Q矩阵）

    Args:
        body: 题目信息（请求体同 POST）
        question_id: 题目 ID

    Returns:
        ApiResponse[QuestionDetail]: 更新后的题目
    """
    try:
        detail = await update_question(
            question_id=question_id,
            content=body.content,
            question_type=body.type,
            difficulty=body.difficulty,
            options=body.options or [],
            answer=body.answer,
            explanation=body.explanation,
            kp_ids=body.knowledge_point_ids,
        )
        if detail is None:
            return ApiResponse.error(
                code=StatusCode.NOT_FOUND,
                message="题目不存在",
            )
        return ApiResponse.success(data=detail, message="更新成功")
    except KnowledgePointMissingError as e:
        return ApiResponse.error(code=StatusCode.BAD_REQUEST, message=str(e))
    except pyodbc.Error as e:
        return _error_sqlserver(e)
    except (DriverError, Neo4jError) as e:
        return _error_neo4j(e)


@router.delete("/{id}", response_model=ApiResponse[None])
async def admin_delete_question(
    question_id: str = Path(..., alias="id", max_length=32, description="题目 ID"),
):
    """删除题目（同步删除 Q矩阵关联）

    Args:
        question_id: 题目 ID

    Returns:
        ApiResponse: 成功时 data 为 null，message 为「删除成功」
    """
    try:
        await delete_question(question_id)
        return ApiResponse.success(data=None, message="删除成功")
    except QuestionNotFoundError:
        return ApiResponse.error(
            code=StatusCode.NOT_FOUND,
            message="题目不存在",
        )
    except pyodbc.Error as e:
        return _error_sqlserver(e)
