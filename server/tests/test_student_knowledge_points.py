"""
学员端知识点接口单元测试

测试覆盖（不依赖真实 Neo4j / SQL Server，可在任何环境运行）：
- 掌握状态阈值计算（纯函数）：mastered / learning / weak / not_started 边界
- Pydantic 响应模型字段与 API 契约一致（status 枚举校验、列表非分页）
- 学员视角列表 / 详情服务聚合逻辑（mock 同步 DB 函数）
- 路由注册正确性 + 数据库不可用时的统一响应格式（{code, data, message}）
"""

import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.student_knowledge_point import (
    StudentKnowledgePointDetail,
    StudentKnowledgePointItem,
    StudentKnowledgePointList,
)
from app.services.student_knowledge_point_service import (
    compute_mastery_status,
    get_student_knowledge_point,
    is_mastered,
    list_student_knowledge_points,
)


class TestMasteryStatus:
    """掌握状态阈值计算（对照契约：mastered ≥0.8 / learning 0.4-0.8 / weak <0.4）"""

    @pytest.mark.parametrize(
        "probability, expected",
        [
            (1.0, "mastered"),
            (0.8, "mastered"),   # 边界：≥0.8 即 mastered
            (0.79, "learning"),
            (0.5, "learning"),
            (0.4, "learning"),   # 边界：0.4 属 learning（weak 为 <0.4）
            (0.39, "weak"),
            (0.0, "weak"),
            (None, "not_started"),
        ],
    )
    def test_compute_mastery_status_boundaries(self, probability, expected):
        """阈值边界与契约一致"""
        assert compute_mastery_status(probability) == expected

    def test_is_mastered(self):
        """前置知识点 mastered = 掌握概率 ≥ 0.8"""
        assert is_mastered(0.8) is True
        assert is_mastered(1.0) is True
        assert is_mastered(0.79) is False
        assert is_mastered(0.0) is False
        assert is_mastered(None) is False


class TestStudentKnowledgePointModels:
    """Pydantic 响应模型（严格对照契约 2.1）"""

    def test_list_item_fields_match_contract(self):
        """列表项字段与契约一致（id/name/chapter_name/difficulty/
        estimated_time/mastery_probability/status）"""
        item = StudentKnowledgePointItem(
            id="kp_001",
            name="一元二次方程的定义",
            chapter_name="一元二次方程",
            difficulty=0.3,
            estimated_time=25,
            mastery_probability=0.92,
            status="mastered",
        )
        dumped = item.model_dump()
        assert set(dumped.keys()) == {
            "id",
            "name",
            "chapter_name",
            "difficulty",
            "estimated_time",
            "mastery_probability",
            "status",
        }

    def test_list_data_is_not_paginated(self):
        """契约规定学员列表 data 为 {list: [...]}，非分页结构（无 total/page）"""
        data = StudentKnowledgePointList(
            list=[
                StudentKnowledgePointItem(
                    id="kp_001",
                    name="测试知识点",
                    chapter_name=None,
                    difficulty=0.3,
                    estimated_time=10,
                    mastery_probability=None,
                    status="not_started",
                )
            ]
        )
        dumped = data.model_dump()
        assert set(dumped.keys()) == {"list"}
        assert "total" not in dumped

    def test_status_rejects_unknown_value(self):
        """status 为受限枚举，非法值校验失败"""
        with pytest.raises(ValidationError):
            StudentKnowledgePointItem(
                id="kp_001",
                name="测试知识点",
                chapter_name=None,
                difficulty=0.3,
                estimated_time=10,
                mastery_probability=0.5,
                status="unknown",
            )

    def test_detail_fields_match_contract(self):
        """详情字段与契约一致（id/name/description/difficulty/
        estimated_time/mastery_probability/prerequisites/questions）"""
        detail = StudentKnowledgePointDetail(
            id="kp_001",
            name="一元二次方程的定义",
            description="理解一元二次方程的标准形式 ax²+bx+c=0",
            difficulty=0.3,
            estimated_time=25,
            mastery_probability=0.92,
            prerequisites=[{"id": "kp_000", "name": "一元一次方程", "mastered": True}],
            questions=[
                {
                    "id": "q_001",
                    "content": "下列哪个是方程 x²-4=0 的解？",
                    "type": "single_choice",
                    "difficulty": 0.3,
                    "done": False,
                }
            ],
        )
        dumped = detail.model_dump()
        assert set(dumped.keys()) == {
            "id",
            "name",
            "description",
            "difficulty",
            "estimated_time",
            "mastery_probability",
            "prerequisites",
            "questions",
        }
        assert dumped["prerequisites"][0]["mastered"] is True
        assert dumped["questions"][0]["done"] is False


class TestStudentKnowledgePointService:
    """服务聚合逻辑（mock 同步 DB 函数，不连接真实数据库）"""

    SAMPLE_KPS = [
        {
            "id": "kp_001",
            "name": "一元二次方程的定义",
            "chapter_name": "一元二次方程",
            "difficulty": 0.3,
            "estimated_time": 25,
        },
        {
            "id": "kp_002",
            "name": "配方法解一元二次方程",
            "chapter_name": "一元二次方程",
            "difficulty": 0.5,
            "estimated_time": 30,
        },
        {
            "id": "kp_003",
            "name": "求根公式推导",
            "chapter_name": None,
            "difficulty": 0.6,
            "estimated_time": 40,
        },
    ]

    @pytest.fixture(autouse=True)
    def _mock_list_db(self, monkeypatch):
        """默认 mock 列表查询的 Neo4j 同步函数"""
        monkeypatch.setattr(
            "app.services.student_knowledge_point_service._db_list_student_kps",
            lambda: self.SAMPLE_KPS,
        )

    def test_list_aggregates_mastery_and_status(self, monkeypatch):
        """列表项聚合掌握概率并计算状态：mastered/learning/not_started"""
        monkeypatch.setattr(
            "app.services.student_knowledge_point_service._db_query_mastery_map",
            lambda user_id, kp_ids: {"kp_001": 0.92, "kp_002": 0.45},
        )
        items = asyncio.run(list_student_knowledge_points("stu_001"))
        by_id = {item.id: item for item in items}
        assert len(items) == 3
        assert by_id["kp_001"].mastery_probability == 0.92
        assert by_id["kp_001"].status == "mastered"
        assert by_id["kp_002"].status == "learning"
        assert by_id["kp_003"].status == "not_started"
        assert by_id["kp_003"].mastery_probability is None

    def test_list_anonymous_all_not_started(self):
        """未登录（user_id=None）时全部 not_started，掌握概率为 None"""
        items = asyncio.run(list_student_knowledge_points(None))
        assert all(item.status == "not_started" for item in items)
        assert all(item.mastery_probability is None for item in items)

    def test_list_mastery_query_failure_degrades(self, monkeypatch):
        """SQL Server 异常时降级为 not_started，不阻塞列表查询"""

        def boom(user_id, kp_ids):
            raise RuntimeError("sql down")

        monkeypatch.setattr(
            "app.services.student_knowledge_point_service._db_query_mastery_map",
            boom,
        )
        items = asyncio.run(list_student_knowledge_points("stu_001"))
        assert all(item.status == "not_started" for item in items)

    def test_detail_aggregates_prerequisites_and_questions(self, monkeypatch):
        """详情聚合前置掌握状态（mastered）与题目完成状态（done）"""
        detail_data = {
            "id": "kp_001",
            "name": "一元二次方程的定义",
            "description": "理解一元二次方程的标准形式 ax²+bx+c=0",
            "difficulty": 0.3,
            "estimated_time": 25,
            "prerequisites": [{"id": "kp_000", "name": "一元一次方程"}],
        }
        monkeypatch.setattr(
            "app.services.student_knowledge_point_service._db_get_student_kp_detail",
            lambda kp_id: detail_data,
        )
        monkeypatch.setattr(
            "app.services.student_knowledge_point_service._db_query_mastery_map",
            lambda user_id, kp_ids: {"kp_001": 0.92, "kp_000": 0.85},
        )
        monkeypatch.setattr(
            "app.services.student_knowledge_point_service._db_query_kp_questions",
            lambda kp_id: [
                {
                    "id": "q_001",
                    "content": "下列哪个是方程 x²-4=0 的解？",
                    "type": "single_choice",
                    "difficulty": 0.3,
                },
                {
                    "id": "q_002",
                    "content": "x²=4 的解是 ±2。",
                    "type": "true_false",
                    "difficulty": 0.2,
                },
            ],
        )
        monkeypatch.setattr(
            "app.services.student_knowledge_point_service._db_query_done_question_ids",
            lambda user_id, question_ids: {"q_001"},
        )

        detail = asyncio.run(get_student_knowledge_point("kp_001", "stu_001"))
        assert detail is not None
        assert detail.mastery_probability == 0.92
        assert detail.prerequisites[0].mastered is True
        assert detail.questions[0].done is True
        assert detail.questions[1].done is False

    def test_detail_prerequisite_not_mastered_when_below_threshold(self, monkeypatch):
        """前置知识点掌握概率 < 0.8 时 mastered 为 False"""
        detail_data = {
            "id": "kp_003",
            "name": "求根公式推导",
            "description": "",
            "difficulty": 0.6,
            "estimated_time": 40,
            "prerequisites": [{"id": "kp_002", "name": "配方法解一元二次方程"}],
        }
        monkeypatch.setattr(
            "app.services.student_knowledge_point_service._db_get_student_kp_detail",
            lambda kp_id: detail_data,
        )
        monkeypatch.setattr(
            "app.services.student_knowledge_point_service._db_query_mastery_map",
            lambda user_id, kp_ids: {"kp_003": 0.45, "kp_002": 0.45},
        )
        monkeypatch.setattr(
            "app.services.student_knowledge_point_service._db_query_kp_questions",
            lambda kp_id: [],
        )
        detail = asyncio.run(get_student_knowledge_point("kp_003", "stu_001"))
        assert detail is not None
        assert detail.prerequisites[0].mastered is False
        assert detail.questions == []

    def test_detail_anonymous_all_unmastered_undone(self, monkeypatch):
        """未登录时前置均未掌握、题目均未做"""
        detail_data = {
            "id": "kp_001",
            "name": "一元二次方程的定义",
            "description": "",
            "difficulty": 0.3,
            "estimated_time": 25,
            "prerequisites": [{"id": "kp_000", "name": "一元一次方程"}],
        }
        monkeypatch.setattr(
            "app.services.student_knowledge_point_service._db_get_student_kp_detail",
            lambda kp_id: detail_data,
        )
        monkeypatch.setattr(
            "app.services.student_knowledge_point_service._db_query_kp_questions",
            lambda kp_id: [
                {
                    "id": "q_001",
                    "content": "x²-4=0 的解？",
                    "type": "single_choice",
                    "difficulty": 0.3,
                }
            ],
        )
        detail = asyncio.run(get_student_knowledge_point("kp_001", None))
        assert detail is not None
        assert detail.mastery_probability is None
        assert detail.prerequisites[0].mastered is False
        assert detail.questions[0].done is False

    def test_detail_not_found(self, monkeypatch):
        """知识点不存在返回 None（router 映射为 40400）"""
        monkeypatch.setattr(
            "app.services.student_knowledge_point_service._db_get_student_kp_detail",
            lambda kp_id: None,
        )
        detail = asyncio.run(get_student_knowledge_point("kp_999", "stu_001"))
        assert detail is None

    def test_detail_sql_failure_degrades(self, monkeypatch):
        """SQL Server 全部异常时详情降级：无掌握数据、题目为空"""
        detail_data = {
            "id": "kp_001",
            "name": "一元二次方程的定义",
            "description": "",
            "difficulty": 0.3,
            "estimated_time": 25,
            "prerequisites": [{"id": "kp_000", "name": "一元一次方程"}],
        }
        monkeypatch.setattr(
            "app.services.student_knowledge_point_service._db_get_student_kp_detail",
            lambda kp_id: detail_data,
        )

        def boom_mastery(user_id, kp_ids):
            raise RuntimeError("sql down")

        def boom_questions(kp_id):
            raise RuntimeError("sql down")

        monkeypatch.setattr(
            "app.services.student_knowledge_point_service._db_query_mastery_map",
            boom_mastery,
        )
        monkeypatch.setattr(
            "app.services.student_knowledge_point_service._db_query_kp_questions",
            boom_questions,
        )
        detail = asyncio.run(get_student_knowledge_point("kp_001", "stu_001"))
        assert detail is not None
        assert detail.mastery_probability is None
        assert detail.prerequisites[0].mastered is False
        assert detail.questions == []


class TestRoutes:
    """路由注册与统一响应格式（mock 数据库连接，不依赖真实 Neo4j）"""

    @pytest.fixture
    def client(self, monkeypatch):
        """mock get_driver：立即抛出 ServiceUnavailable，验证错误处理路径"""
        from neo4j.exceptions import ServiceUnavailable

        def boom_driver():
            raise ServiceUnavailable("Neo4j unavailable (test mock)")

        monkeypatch.setattr(
            "app.services.student_knowledge_point_service.get_driver", boom_driver
        )
        return TestClient(app)

    @pytest.mark.parametrize(
        "path",
        ["/api/student/knowledge-points", "/api/student/knowledge-points/kp_001"],
    )
    def test_routes_registered_not_404(self, client, path):
        """两个接口均已注册（不返回 404；Neo4j 不可用时返回业务码而非路由不存在）"""
        resp = client.get(path)
        assert resp.status_code != 404
        # 统一响应格式：必须含 code/data/message
        body = resp.json()
        assert set(body.keys()) == {"code", "data", "message"}

    def test_list_returns_unified_error_when_neo4j_down(self, client):
        """Neo4j 不可用时列表接口返回统一错误响应（业务码 50002，不抛裸异常）"""
        resp = client.get("/api/student/knowledge-points")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 50002
        assert body["data"] is None
        assert body["message"] == "图数据库异常，请稍后重试"

    def test_detail_returns_unified_error_when_neo4j_down(self, client):
        """Neo4j 不可用时详情接口返回统一错误响应（业务码 50002）"""
        resp = client.get("/api/student/knowledge-points/kp_001")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 50002
        assert body["data"] is None

    def test_invalid_token_falls_back_to_anonymous(self, client):
        """无效 Token 时可选身份解析降级为匿名，接口不因认证失败返回 401"""
        resp = client.get(
            "/api/student/knowledge-points",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # Neo4j 被 mock 为不可用，说明身份解析已成功降级并继续走业务逻辑
        assert body["code"] == 50002
