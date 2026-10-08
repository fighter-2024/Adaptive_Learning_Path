"""学员端路由模块 — 路由前缀 /api/student

需要学生身份的写接口、图谱接口和个性化路径接口自行强制要求有效
student Token；不涉及学生个性化数据的历史只读知识点接口仍保留可选身份行为。
"""

from fastapi import APIRouter

from app.routers.student.health import router as health_router
from app.routers.student.knowledge_points import router as knowledge_points_router
from app.routers.student.answers import router as answers_router
from app.routers.student.diagnosis import router as diagnosis_router
from app.routers.student.path import router as path_router
from app.routers.student.graph import router as graph_router
from app.routers.student.questions import router as questions_router
from app.routers.student.ai import router as ai_router

# 创建 student 子路由。图谱、答题和诊断等需要用户数据的接口在自身路由
# 上强制鉴权；历史只读接口保留兼容性的可选身份行为。
router = APIRouter(prefix="/api/student")

# 注册子路由；路径、图谱、答题和诊断等个性化接口在自身路由上强制鉴权。
router.include_router(health_router, tags=["Student - 健康检查"])
router.include_router(knowledge_points_router, tags=["Student - 知识点"])
router.include_router(answers_router, tags=["Student - 答题"])
router.include_router(diagnosis_router, tags=["Student - 诊断"])
router.include_router(path_router, tags=["Student - 学习路径"])
router.include_router(graph_router, tags=["Student - 图谱"])
router.include_router(questions_router, tags=["Student - 取题"])
router.include_router(ai_router, tags=["Student - AI"])
