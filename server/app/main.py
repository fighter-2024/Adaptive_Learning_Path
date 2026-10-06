"""
FastAPI 应用入口

启动命令：uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.config.security import SensitiveDataFilter
from app.db import check_neo4j_health, check_sqlserver_health, close_driver
from app.models import ApiResponse, StatusCode
from app.routers import admin_router, student_router
from app.routers.auth import router as auth_router

# 配置日志
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# 统一给根 logger 的输出处理器加脱敏过滤，避免异常文本或连接错误回显
# Authorization、API key、密码等敏感字段。
for _handler in logging.getLogger().handlers:
    _handler.addFilter(SensitiveDataFilter())
logger = logging.getLogger(__name__)

# ==================== 生命周期事件 ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化，关闭时释放资源"""
    logger.info("应用启动，配置: %s v%s", settings.APP_NAME, settings.APP_VERSION)
    # 打印实际生效的数据库连接参数（不含密码）：连接失败时可直接对照排查，
    # 不必再怀疑是实例配置、驱动还是 .env 未生效。
    logger.info("SQL Server 有效配置: %s", settings.describe_sqlserver())
    logger.info("Neo4j 有效配置: %s (用户: %s)", settings.NEO4J_URI, settings.NEO4J_USER)
    yield
    logger.info("应用关闭中，释放数据库连接...")
    close_driver()
    logger.info("数据库连接已释放，应用退出")


app = FastAPI(
    title=settings.APP_NAME,
    description="基于知识图谱的自适应学习路径规划与社交激励系统",
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

# CORS 中间件：来源白名单读自 settings.CORS_ALLOW_ORIGINS（.env 可配）。
# 按 CORS 规范，通配符 "*" 与 allow_credentials 互斥：
# - 配置为 "*"（默认，开发环境）时不携带凭证；
# - 配置为具体来源列表时启用 allow_credentials=True。
_cors_origins = [o.strip() for o in settings.CORS_ALLOW_ORIGINS.split(",") if o.strip()] or ["*"]
_cors_allow_credentials = "*" not in _cors_origins
logger.info(
    "CORS 配置: origins=%s, allow_credentials=%s",
    _cors_origins,
    _cors_allow_credentials,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 全局异常处理器 ====================

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """请求参数校验失败时返回统一响应格式（HTTP 422 + 业务码 40000）

    按 AI 开发总则要求，所有响应（含校验失败）统一为 {code, data, message}，
    不暴露 Pydantic 默认的 detail 结构。
    """
    details = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", []) if x != "body")
        details.append(f"{loc or '请求参数'}: {err.get('msg', '校验失败')}")
    message = "请求参数校验失败：" + "；".join(details)
    logger.warning("参数校验失败: %s %s - %s", request.method, request.url.path, message)
    return JSONResponse(
        status_code=422,
        content=ApiResponse.error(
            code=StatusCode.BAD_REQUEST,
            message=message,
        ).model_dump(),
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """将 HTTPException 转为统一响应格式（总则第四条：所有响应统一 {code, data, message}）

    依赖层抛出的 HTTPException（鉴权 401/403、速率限制 429 等）的 detail
    已是 ApiResponse 字典，FastAPI 默认会再包一层 {"detail": {...}}，
    这里拆掉该包裹直接返回统一格式；其他来源的 HTTPException 按状态码
    归类业务码后包装。
    """
    if exc.status_code in (204, 304):
        # 不允许携带响应体的状态码
        return Response(status_code=exc.status_code, headers=exc.headers)

    detail = exc.detail
    if isinstance(detail, dict) and set(detail.keys()) == {"code", "data", "message"}:
        body = detail
    else:
        code = (
            StatusCode.BAD_REQUEST
            if 400 <= exc.status_code < 500
            else StatusCode.INTERNAL_ERROR
        )
        message = (
            str(detail)
            if isinstance(detail, (str, int, float))
            else "请求处理失败"
        )
        logger.warning(
            "HTTPException 未按统一格式抛出: %s %s (%d) - %s",
            request.method,
            request.url.path,
            exc.status_code,
            message,
        )
        body = ApiResponse.error(code=code, message=message).model_dump()
    return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """将未捕获异常转为统一响应格式，避免向客户端暴露内部堆栈"""
    logger.exception("未处理异常: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=ApiResponse.error(
            code=StatusCode.INTERNAL_ERROR,
            message="服务器内部错误，请稍后重试",
        ).model_dump(),
    )


# ==================== 注册路由 ====================

app.include_router(admin_router)
app.include_router(student_router)
app.include_router(auth_router)


# ==================== 全局接口 ====================

@app.get("/", response_model=ApiResponse[dict])
async def root():
    """应用根路径，返回基本服务信息"""
    return ApiResponse.success(
        data={"service": settings.APP_NAME, "version": settings.APP_VERSION},
        message="服务运行中",
    )


@app.get("/health", response_model=ApiResponse[dict])
async def health():
    """全局健康检查

    检测 Neo4j 和 SQL Server 的连通性。
    即使数据库不可用也返回 200，通过 data 字段中的布尔值区分状态。

    Returns:
        ApiResponse: data 中含 status、neo4j、sqlserver 三个字段
    """
    neo4j_ok = await check_neo4j_health()
    sqlserver_ok = await check_sqlserver_health()
    all_ok = neo4j_ok and sqlserver_ok

    return ApiResponse.success(
        data={
            "status": "ok" if all_ok else "degraded",
            "neo4j": neo4j_ok,
            "sqlserver": sqlserver_ok,
        },
        message="所有服务正常" if all_ok else "部分服务不可用，请检查配置",
    )
