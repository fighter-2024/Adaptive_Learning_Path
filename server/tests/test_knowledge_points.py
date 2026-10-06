"""
知识点管理模块单元测试

测试覆盖（不依赖真实 Neo4j / SQL Server，可在任何环境运行）：
- Pydantic 请求/响应模型校验
- 环检测、ID 生成等纯函数逻辑
- 路由注册正确性（请求不会 404）
- 数据库不可用时的统一响应格式（{code, data, message}）
"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.auth import UserInfo
from app.models.knowledge_point import (
    KnowledgePointCreateRequest,
    KnowledgePointDetail,
    KnowledgePointItem,
    PrerequisitesUpdateRequest,
)
from app.routers.dependencies import get_current_user, require_admin
from app.services.knowledge_point_service import (
    _generate_kp_id,
    detect_cycles,
    sanitize_kp_list_row,
)


class TestKnowledgePointModels:
    """Pydantic 模型校验"""

    def test_create_request_valid(self):
        """正常创建请求"""
        req = KnowledgePointCreateRequest(
            name="一元二次方程的定义",
            description="理解标准形式 ax²+bx+c=0",
            chapter_id="ch_03",
            difficulty=0.3,
            estimated_time=25,
        )
        assert req.name == "一元二次方程的定义"
        assert req.difficulty == 0.3
        assert req.estimated_time == 25
        # description 可省略，默认空字符串
        req2 = KnowledgePointCreateRequest(
            name="测试", chapter_id="ch_01", difficulty=0.2, estimated_time=10
        )
        assert req2.description == ""

    def test_create_request_invalid_difficulty(self):
        """难度超出 0~1 范围"""
        with pytest.raises(ValidationError):
            KnowledgePointCreateRequest(
                name="测试", chapter_id="ch_01", difficulty=1.5, estimated_time=10
            )
        with pytest.raises(ValidationError):
            KnowledgePointCreateRequest(
                name="测试", chapter_id="ch_01", difficulty=-0.1, estimated_time=10
            )

    def test_create_request_invalid_estimated_time(self):
        """学习时长必须为正整数"""
        with pytest.raises(ValidationError):
            KnowledgePointCreateRequest(
                name="测试", chapter_id="ch_01", difficulty=0.3, estimated_time=0
            )

    def test_create_request_name_required(self):
        """名称必填且非空"""
        with pytest.raises(ValidationError):
            KnowledgePointCreateRequest(
                name="", chapter_id="ch_01", difficulty=0.3, estimated_time=10
            )

    def test_create_request_chapter_id_required(self):
        """章节 ID 必填"""
        with pytest.raises(ValidationError):
            KnowledgePointCreateRequest(
                name="测试", difficulty=0.3, estimated_time=10
            )

    def test_prerequisites_request_default_empty(self):
        """前置依赖请求体默认为空列表（表示清空）"""
        req = PrerequisitesUpdateRequest()
        assert req.prerequisite_ids == []
        req2 = PrerequisitesUpdateRequest(prerequisite_ids=["kp_001", "kp_002"])
        assert req2.prerequisite_ids == ["kp_001", "kp_002"]

    def test_item_model_fields(self):
        """列表项模型字段与 API 契约一致"""
        item = KnowledgePointItem(
            id="kp_001",
            name="一元二次方程的定义",
            description="理解标准形式",
            chapter_id="ch_01",
            chapter_name="一元二次方程",
            difficulty=0.3,
            estimated_time=25,
            prerequisite_count=2,
            question_count=5,
            created_at="2026-01-15T10:00:00",
        )
        dumped = item.model_dump()
        for field in (
            "id", "name", "description", "chapter_id", "chapter_name",
            "difficulty", "estimated_time", "prerequisite_count",
            "question_count", "created_at",
        ):
            assert field in dumped

    def test_detail_model_fields(self):
        """详情模型字段与 API 契约一致（含 prerequisites/dependents）"""
        detail = KnowledgePointDetail(
            id="kp_001",
            name="一元二次方程的定义",
            description="理解标准形式",
            chapter_id="ch_01",
            chapter_name="一元二次方程",
            difficulty=0.3,
            estimated_time=25,
            prerequisites=[{"id": "kp_000", "name": "一元一次方程"}],
            dependents=[{"id": "kp_002", "name": "配方法解一元二次方程"}],
        )
        dumped = detail.model_dump()
        assert dumped["prerequisites"] == [{"id": "kp_000", "name": "一元一次方程"}]
        assert dumped["dependents"][0]["id"] == "kp_002"


class TestDetectCycles:
    """前置依赖环检测（纯函数）"""

    def test_no_cycle(self):
        """无环图返回空列表"""
        edges = [("a", "b"), ("b", "c"), ("a", "c")]
        assert detect_cycles(edges) == []

    def test_simple_cycle(self):
        """两节点互指形成环"""
        cycles = detect_cycles([("a", "b"), ("b", "a")])
        assert len(cycles) == 1
        assert set(cycles[0]) == {"a", "b"}

    def test_self_loop(self):
        """自环"""
        cycles = detect_cycles([("a", "a")])
        assert len(cycles) == 1

    def test_three_node_cycle(self):
        """三节点环"""
        cycles = detect_cycles([("a", "b"), ("b", "c"), ("c", "a")])
        assert len(cycles) == 1
        assert len(cycles[0]) == 4  # 首尾重复的环路径

    def test_dag_with_cross_edges(self):
        """典型 DAG（链式 + 跨层边）无环"""
        edges = [
            ("kp_001", "kp_002"),
            ("kp_002", "kp_003"),
            ("kp_001", "kp_003"),
            ("kp_003", "kp_004"),
            ("kp_002", "kp_004"),
        ]
        assert detect_cycles(edges) == []

    def test_empty_edges(self):
        """空边集无环"""
        assert detect_cycles([]) == []


class TestKpIDGeneration:
    """业务 ID 生成"""

    def test_id_prefix(self):
        """ID 以 kp_ 开头"""
        assert _generate_kp_id().startswith("kp_")

    def test_id_format(self):
        """ID 格式: kp_xxxxxxxx (8 位十六进制)"""
        import re

        assert re.match(r"^kp_[0-9a-f]{8}$", _generate_kp_id()) is not None

    def test_id_unique(self):
        """每次生成不同 ID"""
        ids = {_generate_kp_id() for _ in range(100)}
        assert len(ids) == 100


class TestRoutes:
    """路由注册与统一响应格式（mock 数据库连接，不依赖真实 Neo4j）"""

    @pytest.fixture
    def client(self, monkeypatch):
        """mock get_driver：立即抛出 ServiceUnavailable，验证错误处理路径；
        同时以管理员身份覆盖 require_admin 依赖（管理接口已启用鉴权，
        用依赖覆盖模拟"已登录的管理员"，与答题/诊断模块的测试手法一致）"""
        from neo4j.exceptions import ServiceUnavailable

        def boom_driver():
            raise ServiceUnavailable("Neo4j unavailable (test mock)")

        fake_admin = UserInfo(
            user_id="adm_001", username="admin_wang", name="王管理", role="admin"
        )
        monkeypatch.setattr(
            "app.services.knowledge_point_service.get_driver", boom_driver
        )
        app.dependency_overrides[require_admin] = lambda: fake_admin
        yield TestClient(app)
        app.dependency_overrides.clear()

    def test_admin_endpoints_require_auth(self):
        """管理接口已启用鉴权：未携带 Token 返回 401"""
        client = TestClient(app)
        resp = client.get("/api/admin/knowledge-points?page=1&page_size=10")
        assert resp.status_code == 401
        assert resp.json()["code"] == 40100

        resp = client.post(
            "/api/admin/knowledge-points",
            json={
                "name": "测试知识点",
                "chapter_id": "ch_01",
                "difficulty": 0.3,
                "estimated_time": 10,
            },
        )
        assert resp.status_code == 401

    def test_admin_endpoints_reject_student_role(self, monkeypatch):
        """学生角色的 Token 访问管理接口返回 403"""
        fake_student = UserInfo(
            user_id="stu_001", username="zhangsan", name="张三", role="student"
        )
        app.dependency_overrides[get_current_user] = lambda: fake_student
        client = TestClient(app)
        try:
            resp = client.get("/api/admin/knowledge-points?page=1&page_size=10")
            assert resp.status_code == 403
            assert resp.json()["code"] == 40101
        finally:
            app.dependency_overrides.clear()

    def test_sanitize_kp_list_row_null_tolerance(self):
        """历史数据缺属性时补默认值，避免 Pydantic 校验失败（500）"""
        row = sanitize_kp_list_row(
            {
                "id": "kp_legacy",
                "name": "历史知识点",
                "description": None,
                "chapter_id": None,
                "chapter_name": None,
                "difficulty": None,
                "estimated_time": None,
                "prerequisite_count": None,
                "created_at": None,
            }
        )
        assert row["description"] == ""
        assert row["chapter_id"] == ""
        assert row["difficulty"] == 0.0
        assert row["estimated_time"] == 0
        assert row["prerequisite_count"] == 0
        # 兜底后的行能通过列表项模型校验（原实现会抛 ValidationError → 500）
        item = KnowledgePointItem(**row)
        assert item.id == "kp_legacy"

    @pytest.mark.parametrize(
        "method, path",
        [
            ("GET", "/api/admin/knowledge-points"),
            ("GET", "/api/admin/knowledge-points/kp_001"),
            ("POST", "/api/admin/knowledge-points"),
            ("PUT", "/api/admin/knowledge-points/kp_001"),
            ("DELETE", "/api/admin/knowledge-points/kp_001"),
            ("POST", "/api/admin/knowledge-points/kp_001/prerequisites"),
        ],
    )
    def test_routes_registered_not_404(self, client, method, path):
        """六个接口均已注册（不返回 404；Neo4j 不可用时返回业务码而非路由不存在）"""
        payload = {}
        if method == "POST" and path.endswith("/knowledge-points"):
            payload = {
                "name": "测试知识点",
                "chapter_id": "ch_01",
                "difficulty": 0.3,
                "estimated_time": 10,
            }
        elif method == "POST" and path.endswith("/prerequisites"):
            payload = {"prerequisite_ids": []}
        elif method == "PUT":
            payload = {
                "name": "测试知识点",
                "chapter_id": "ch_01",
                "difficulty": 0.3,
                "estimated_time": 10,
            }

        resp = client.request(method, path, json=payload)
        assert resp.status_code != 404
        # 统一响应格式：必须含 code/data/message
        body = resp.json()
        assert set(body.keys()) == {"code", "data", "message"}

    def test_list_returns_unified_error_when_neo4j_down(self, client):
        """Neo4j 不可用时列表接口返回统一错误响应（业务码 50002，不抛裸异常）"""
        resp = client.get("/api/admin/knowledge-points?page=1&page_size=10")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 50002
        assert body["data"] is None
        assert body["message"] == "图数据库异常，请稍后重试"

    def test_invalid_payload_returns_unified_validation_error(self, client):
        """参数校验失败返回统一格式（HTTP 422 + code 40000），而非 Pydantic 默认 detail"""
        resp = client.post(
            "/api/admin/knowledge-points",
            json={
                "name": "测试",
                "chapter_id": "ch_01",
                "difficulty": 1.5,  # 超出 0~1
                "estimated_time": 10,
            },
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == 40000
        assert body["data"] is None
        assert "difficulty" in body["message"] or "校验失败" in body["message"]

    def test_page_size_over_max_rejected(self, client):
        """page_size 超过 100 被参数校验拦截"""
        resp = client.get("/api/admin/knowledge-points?page=1&page_size=101")
        assert resp.status_code == 422
        assert resp.json()["code"] == 40000

    def test_invalid_prerequisites_payload_rejected(self, client):
        """前置依赖请求体不是字符串数组时校验失败"""
        resp = client.post(
            "/api/admin/knowledge-points/kp_001/prerequisites",
            json={"prerequisite_ids": "kp_000"},
        )
        assert resp.status_code == 422
        assert resp.json()["code"] == 40000
