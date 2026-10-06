"""API 路由总模块"""

from app.routers.admin import router as admin_router
from app.routers.student import router as student_router

__all__ = ["admin_router", "student_router"]
