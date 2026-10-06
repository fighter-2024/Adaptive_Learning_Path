"""
统一响应模型

所有 API 接口返回格式：
    {"code": 0, "data": ..., "message": ""}

code=0 表示成功，非 0 表示异常（见 status_code.py）。
"""

from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一 API 响应外壳

    Attributes:
        code: 业务状态码，0 表示成功
        data: 响应数据，成功时返回对应数据，失败时为 None
        message: 提示信息，成功时可为空，失败时描述错误原因
    """

    code: int = 0
    data: Optional[T] = None
    message: str = ""

    @classmethod
    def success(cls, data: T, message: str = "成功") -> "ApiResponse[T]":
        """构建成功响应"""
        return cls(code=0, data=data, message=message)

    @classmethod
    def error(cls, code: int, message: str, data: Any = None) -> "ApiResponse":
        """构建错误响应"""
        return cls(code=code, data=data, message=message)


class PaginatedData(BaseModel, Generic[T]):
    """分页数据结构

    Attributes:
        list: 当前页数据列表（字段名与 API 契约一致）
        total: 总记录数
        page: 当前页码（从 1 开始）
        page_size: 每页条数
    """

    # 使用 typing.List 避免与字段名 list 冲突
    list: List[T] = []  # noqa: A003
    total: int = 0
    page: int = 1
    page_size: int = 20
