"""
路由层 JWT 认证依赖注入

提供可复用的 FastAPI Depends 函数，用于在路由层校验用户身份。
Router 只做路由和参数校验，认证逻辑委托给本模块和 service 层。
"""

import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.models.auth import UserInfo
from app.models.response import ApiResponse
from app.models.status_code import STATUS_MESSAGES, StatusCode
from app.services.auth_service import decode_jwt_token, get_user_by_id
from app.services.rate_limiter import RateLimitExceededError, check_rate_limit

logger = logging.getLogger(__name__)

# HTTP Bearer 认证方案
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> UserInfo:
    """从请求 Header 解析 JWT 并返回当前用户信息

    作为 FastAPI 依赖注入使用：
        @router.get("/me")
        async def me(current_user: UserInfo = Depends(get_current_user)):
            ...

    Args:
        credentials: 从 Authorization: Bearer <token> 中提取的凭证

    Returns:
        当前登录用户的 UserInfo

    Raises:
        HTTPException 401: Token 缺失、过期、无效或用户不存在
    """
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail=ApiResponse.error(
                code=StatusCode.UNAUTHORIZED,
                message=STATUS_MESSAGES[StatusCode.UNAUTHORIZED],
            ).model_dump(),
        )

    token = credentials.credentials

    # 解析 JWT
    try:
        payload = decode_jwt_token(token)
    except Exception:
        logger.warning("JWT 解析失败")
        raise HTTPException(
            status_code=401,
            detail=ApiResponse.error(
                code=StatusCode.UNAUTHORIZED,
                message="登录凭证无效或已过期，请重新登录",
            ).model_dump(),
        )

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail=ApiResponse.error(
                code=StatusCode.UNAUTHORIZED,
                message="登录凭证无效",
            ).model_dump(),
        )

    # 查询用户信息
    user = await get_user_by_id(user_id)
    if user is None:
        logger.warning("JWT 有效但用户不存在: user_id=%s", user_id)
        raise HTTPException(
            status_code=401,
            detail=ApiResponse.error(
                code=StatusCode.UNAUTHORIZED,
                message="用户不存在或已被禁用",
            ).model_dump(),
        )

    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> Optional[UserInfo]:
    """尽力解析当前用户；无 Token 或凭证无效时返回 None（匿名）

    供学员端接口在全局 JWT 认证尚未启用期间提前获得用户身份
    （见 routers/student/__init__.py 的占位说明）：携带有效 Token 时
    按学员视角返回个性化数据，否则降级为匿名视角。

    Args:
        credentials: 从 Authorization: Bearer <token> 中提取的凭证

    Returns:
        UserInfo 或 None（未携带 Token / 凭证无效 / 用户不存在）
    """
    if credentials is None:
        return None
    try:
        return await get_current_user(credentials)
    except Exception as e:
        # 可选身份：任何解析/查询失败都降级为匿名，不阻断请求。
        # 不打印堆栈（客户端携带过期/伪造 Token 属常见情况，避免日志噪音），
        # 需要排查时再打开 DEBUG 日志。
        logger.warning("可选身份解析失败，按匿名用户处理: %s", e)
        return None


# ==================== 认证接口速率限制（防暴力破解） ====================


async def _apply_rate_limit(
    request: Request, key_prefix: str, max_attempts: int, window_seconds: int
) -> None:
    """按客户端 IP 执行速率限制，超限时抛 HTTP 429（统一响应格式）

    Args:
        request: 当前请求（取客户端 IP）
        key_prefix: 限流键前缀（区分登录/注册）
        max_attempts: 窗口内最大请求次数（读自 settings）
        window_seconds: 滑动窗口长度（秒，读自 settings）

    Raises:
        HTTPException 429: 触发速率限制
    """
    client_ip = request.client.host if request.client else "unknown"
    key = f"{key_prefix}:{client_ip}"
    try:
        check_rate_limit(key, max_attempts, window_seconds)
    except RateLimitExceededError as e:
        raise HTTPException(
            status_code=429,
            detail=ApiResponse.error(
                code=StatusCode.TOO_MANY_REQUESTS,
                message=str(e),
            ).model_dump(),
        )


async def login_rate_limit(request: Request) -> None:
    """登录接口速率限制（按客户端 IP，阈值读 settings，.env 可配）"""
    await _apply_rate_limit(
        request,
        "login",
        settings.RATE_LIMIT_LOGIN_MAX_ATTEMPTS,
        settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS,
    )


async def register_rate_limit(request: Request) -> None:
    """注册接口速率限制（按客户端 IP，阈值读 settings，.env 可配）"""
    await _apply_rate_limit(
        request,
        "register",
        settings.RATE_LIMIT_REGISTER_MAX_ATTEMPTS,
        settings.RATE_LIMIT_REGISTER_WINDOW_SECONDS,
    )


# ==================== 可选的权限校验（后续启用） ====================


async def require_admin(
    current_user: UserInfo = Depends(get_current_user),
) -> UserInfo:
    """要求当前用户是管理员，否则返回 403

    Args:
        current_user: 当前登录用户

    Returns:
        当前管理员用户的 UserInfo

    Raises:
        HTTPException 403: 当前用户非管理员
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail=ApiResponse.error(
                code=StatusCode.FORBIDDEN,
                message="仅管理员可访问此接口",
            ).model_dump(),
        )
    return current_user


async def require_student(
    current_user: UserInfo = Depends(get_current_user),
) -> UserInfo:
    """要求当前用户是学生，否则返回 403

    Args:
        current_user: 当前登录用户

    Returns:
        当前学生用户的 UserInfo

    Raises:
        HTTPException 403: 当前用户非学生
    """
    if current_user.role != "student":
        raise HTTPException(
            status_code=403,
            detail=ApiResponse.error(
                code=StatusCode.FORBIDDEN,
                message="仅学生可访问此接口",
            ).model_dump(),
        )
    return current_user
