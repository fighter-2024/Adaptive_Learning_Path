"""项目骨架初始化验证 — 确认所有模块可正确导入"""

import pytest


class TestImports:
    """验证核心模块导入"""

    def test_config_import(self):
        """配置模块可正确导入且 settings 包含必要字段"""
        from app.config import settings

        assert settings.APP_NAME == "Adaptive Learning System"
        assert settings.NEO4J_URI.startswith("bolt://")
        assert settings.SQLSERVER_DRIVER == "ODBC Driver 17 for SQL Server"
        assert settings.DINA_EM_MAX_ITERATIONS == 500
        assert settings.JWT_EXPIRE_MINUTES == 1440

    def test_models_import(self):
        """统一响应模型可正确导入"""
        from app.models import ApiResponse, PaginatedData, StatusCode

        # 验证 ApiResponse
        resp = ApiResponse.success(data={"test": True})
        assert resp.code == 0
        assert resp.data == {"test": True}

        resp_err = ApiResponse.error(code=40000, message="参数错误")
        assert resp_err.code == 40000
        assert resp_err.message == "参数错误"

        # 验证状态码
        assert StatusCode.SUCCESS == 0
        assert StatusCode.KNOWLEDGE_POINT_HAS_DEPENDENTS == 40001
        assert StatusCode.INTERNAL_ERROR == 50000
        assert StatusCode.LLM_ERROR == 60000

        # 验证分页
        # 验证分页（字段名 list 与 API 契约一致，Python 侧用 typing.List 避免冲突）
        page = PaginatedData(list=[1, 2, 3], total=10, page=1, page_size=3)
        assert page.total == 10
        assert len(page.list) == 3
        # 验证 JSON 序列化字段名为 "list"
        json_data = page.model_dump()
        assert "list" in json_data
        assert json_data["list"] == [1, 2, 3]

    def test_db_modules_exist(self):
        """数据库连接模块存在且可导入"""
        from app.db import get_driver, get_connection, check_neo4j_health, check_sqlserver_health

        # 验证函数可调用（不实际连接）
        assert callable(get_driver)
        assert callable(get_connection)
        assert callable(check_neo4j_health)
        assert callable(check_sqlserver_health)

    def test_routers_import(self):
        """路由模块可正确导入且含预期前缀"""
        from app.routers import admin_router, student_router

        assert admin_router.prefix == "/api/admin"
        assert student_router.prefix == "/api/student"

    def test_main_app_import(self):
        """FastAPI 应用实例可正确创建"""
        from app.main import app

        assert app.title == "Adaptive Learning System"
        # 验证关键路由已注册（子路由路径不以纯字符串出现在顶层 routes）
        route_paths = []
        for route in app.routes:
            path = getattr(route, "path", "")
            route_paths.append(path)
        assert "/" in route_paths
        assert "/health" in route_paths
