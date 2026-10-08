"""管理后台路由模块 — 路由前缀 /api/admin

知识图谱、题库等管理业务接口统一启用管理员身份校验，未携带有效管理员
Token 返回 401，非管理员角色返回 403。健康检查保持公开，供部署探针使用。
"""

from fastapi import APIRouter, Depends

from app.routers.admin.health import router as health_router
from app.routers.admin.graph import router as graph_router
from app.routers.admin.knowledge_points import router as knowledge_points_router
from app.routers.admin.questions import router as questions_router
from app.routers.admin.config import router as config_router
from app.routers.admin.dashboard import router as dashboard_router
from app.routers.admin.students import router as students_router
from app.routers.dependencies import require_admin
from app.routers.admin.ai_reports import router as ai_reports_router

# 创建 admin 子路由；业务子路由单独挂载管理员身份校验，健康检查保持公开。
router = APIRouter(prefix="/api/admin")
router.include_router(ai_reports_router, tags=["Admin - AI报告"], dependencies=[Depends(require_admin)])

# 注册子路由（路由级依赖统一要求管理员身份）
router.include_router(health_router, tags=["Admin - 健康检查"])
router.include_router(
    graph_router,
    tags=["Admin - 图谱读取"],
    dependencies=[Depends(require_admin)],
)
router.include_router(
    knowledge_points_router,
    tags=["Admin - 知识点管理"],
    dependencies=[Depends(require_admin)],
)
router.include_router(
    questions_router,
    tags=["Admin - 题库管理"],
    dependencies=[Depends(require_admin)],
)
router.include_router(
    config_router,
    tags=["Admin - 系统配置"],
    dependencies=[Depends(require_admin)],
)
router.include_router(
    dashboard_router,
    tags=["Admin - 仪表盘"],
    dependencies=[Depends(require_admin)],
)
router.include_router(
    students_router,
    tags=["Admin - 学生数据"],
    dependencies=[Depends(require_admin)],
)
