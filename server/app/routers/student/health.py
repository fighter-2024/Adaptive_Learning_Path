"""学员端路由 — 健康检查占位接口

后续启用 JWT 认证示例：
    from app.routers.dependencies import require_student
    @router.get("/health", dependencies=[Depends(require_student)])
"""

from fastapi import APIRouter

from app.models import ApiResponse

router = APIRouter()


@router.get("/health", response_model=ApiResponse[dict])
async def student_health():
    """学员端健康检查占位接口

    Returns:
        ApiResponse: 统一响应格式，data 中包含服务标识
    """
    return ApiResponse.success(
        data={"service": "student", "status": "ok"},
        message="学员端服务正常",
    )
