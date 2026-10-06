"""
认证路由 — 用户注册、登录、获取当前用户信息

路由前缀 /auth，不加 /api/ 前缀（认证是通用模块，不属于 admin/student）。
Router 只做路由和参数校验，业务逻辑委托给 service 层。
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException

from app.models.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserInfo,
)
from app.models.response import ApiResponse
from app.models.status_code import STATUS_MESSAGES, StatusCode
from app.routers.dependencies import (
    get_current_user,
    login_rate_limit,
    register_rate_limit,
)
from app.services.auth_service import get_user_by_id, login, register

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", response_model=ApiResponse[UserInfo])
async def auth_register(
    _rate_limit: Annotated[None, Depends(register_rate_limit)],
    body: Annotated[RegisterRequest, Body()],
):
    """注册新用户

    默认角色为 student，仅允许注册 student 账号。
    管理员账号需由已有管理员在后台创建。
    接口带速率限制（按客户端 IP，防批量注册/暴力破解）。

    Args:
        _rate_limit: 速率限制依赖（声明在前，先于请求体校验执行）
        body: 注册请求体，含 username / password / name / role

    Returns:
        ApiResponse[UserInfo]: 新创建的用户信息
    """
    # 安全约束：对外开放注册仅允许 student 角色，
    # 管理员账号需由已有管理员在后台创建。
    # 按业务码总表约定：角色不符 → HTTP 403（业务码 40101）。
    if body.role != "student":
        raise HTTPException(
            status_code=403,
            detail=ApiResponse.error(
                code=StatusCode.FORBIDDEN,
                message="仅允许注册学生账号",
            ).model_dump(),
        )

    try:
        user = await register(
            username=body.username,
            password=body.password,
            name=body.name,
            role="student",
        )
        logger.info("用户注册成功: %s (%s)", user.username, user.user_id)
        return ApiResponse.success(data=user, message="注册成功")
    except ValueError as e:
        return ApiResponse.error(
            code=StatusCode.CONFLICT,
            message=str(e),
        )


@router.post("/login", response_model=ApiResponse[TokenResponse])
async def auth_login(
    _rate_limit: Annotated[None, Depends(login_rate_limit)],
    body: Annotated[LoginRequest, Body()],
):
    """用户登录

    校验用户名密码，成功返回 JWT Token。
    接口带速率限制（按客户端 IP，防暴力破解）。

    Args:
        _rate_limit: 速率限制依赖（声明在前，先于请求体校验执行）
        body: 登录请求体，含 username / password

    Returns:
        ApiResponse[TokenResponse]: JWT 令牌及过期信息
    """
    try:
        token_resp = await login(
            username=body.username,
            password=body.password,
        )
        logger.info("用户登录成功: %s", body.username)
        return ApiResponse.success(data=token_resp, message="登录成功")
    except ValueError as e:
        # 按业务码总表约定：凭证错误/账号禁用 → HTTP 401（业务码 40100）
        logger.warning("登录失败: username=%s - %s", body.username, e)
        raise HTTPException(
            status_code=401,
            detail=ApiResponse.error(
                code=StatusCode.UNAUTHORIZED,
                message=str(e),
            ).model_dump(),
        )


@router.get("/me", response_model=ApiResponse[UserInfo])
async def auth_me(current_user: UserInfo = Depends(get_current_user)):
    """获取当前登录用户信息

    需在 Header 中携带 Authorization: Bearer <token>。
    Token 无效或过期返回 401。

    Args:
        current_user: 通过 JWT 依赖注入获取的当前用户

    Returns:
        ApiResponse[UserInfo]: 当前用户信息
    """
    return ApiResponse.success(data=current_user, message="获取成功")
