"""
认证相关 Pydantic 数据模型

定义注册/登录请求体和用户信息响应体。
所有字段通过 Pydantic 自动校验，不手写校验逻辑。
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    """注册请求体

    Attributes:
        username: 登录账号，3-50 字符
        password: 明文密码，最少 6 字符（存储前会 bcrypt 哈希）
        name: 显示名称
        role: 角色，默认为 student，仅允许 student/admin
    """

    username: str = Field(..., min_length=3, max_length=50, description="登录账号")
    password: str = Field(..., min_length=6, max_length=100, description="密码")
    name: str = Field(..., min_length=1, max_length=50, description="显示名称")
    role: str = Field(default="student", pattern=r"^(student|admin)$", description="角色")


class LoginRequest(BaseModel):
    """登录请求体

    Attributes:
        username: 登录账号
        password: 明文密码
    """

    username: str = Field(..., min_length=1, description="登录账号")
    password: str = Field(..., min_length=1, description="密码")


class TokenResponse(BaseModel):
    """JWT Token 响应体

    Attributes:
        token: JWT 访问令牌
        token_type: 令牌类型，固定为 "Bearer"
        expires_in: 过期剩余秒数
    """

    token: str = Field(..., description="JWT 访问令牌")
    token_type: str = Field(default="Bearer", description="令牌类型")
    expires_in: int = Field(..., description="过期剩余秒数")


class UserInfo(BaseModel):
    """用户信息响应体

    Attributes:
        user_id: 业务 ID，如 stu_001
        username: 登录账号
        name: 显示名称
        role: 角色
        avatar: 头像 URL，可为空
    """

    user_id: str
    username: str
    name: str
    role: str
    avatar: Optional[str] = None
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
