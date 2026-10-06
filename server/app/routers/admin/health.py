"""管理后台路由 — 健康检查占位接口

后续启用 JWT 认证示例：
    from app.routers.dependencies import require_admin
    @router.get("/health", dependencies=[Depends(require_admin)])
"""

from fastapi import APIRouter

from app.models import ApiResponse

router = APIRouter()


@router.get("/health", response_model=ApiResponse[dict])
async def admin_health():
    """管理后台健康检查占位接口

    Returns:
        ApiResponse: 统一响应格式，data 中包含服务标识
    """
    return ApiResponse.success(
        data={"service": "admin", "status": "ok"},
        message="管理后台服务正常",
    )
