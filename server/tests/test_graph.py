"""M3 学生/管理端图谱接口与聚合服务测试。"""

import asyncio

import pytest
from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable

from app.main import app
from app.models.auth import UserInfo
from app.models.graph import GraphData
from app.routers.dependencies import require_student
from app.services.graph_service import (
    CandidateSelection,
    GraphFocusNotFoundError,
    GraphNeo4jError,
    GraphSqlServerError,
    _build_graph_data,
    _db_load_graph_rows,
    _db_query_mastery_map,
    get_student_graph,
    get_student_neighbors,
)
from app.services.learning_path_service import KnowledgeGraphCycleError


STUDENT = UserInfo(user_id="stu_a", username="a", name="学生 A", role="student")


def _rows(count: int = 3) -> dict:
    """生成可重复的图谱模拟行。"""
    knowledge_points = [
        {
            "id": f"kp_{i:03d}",
            "name": f"知识点 {i}",
            "chapter_id": "ch_01",
            "difficulty": 0.2,
            "estimated_time": 20,
        }
        for i in range(count)
    ]
    prerequisites = [
        {"id": f"pre_kp_{i - 1:03d}_kp_{i:03d}", "source": f"kp_{i - 1:03d}", "target": f"kp_{i:03d}"}
        for i in range(1, count)
    ]
    return {
        "knowledge_points": knowledge_points,
        "chapters": [{"id": "ch_01", "name": "第一章"}],
        "prerequisites": prerequisites,
    }


class TestGraphModelsAndService:
    """标准结构、截断、批量掌握度和管理端隔离。"""

    def test_500_nodes_are_truncated_and_counts_are_consistent(self, monkeypatch):
        """500 个模拟节点只返回 max_nodes，且不按节点逐条查 SQL。"""
        candidate_ids = [f"kp_{i:03d}" for i in range(500)]
        rows = _rows(500)
        mastery_calls = []

        monkeypatch.setattr(
            "app.services.graph_service._db_query_candidate_ids",
            lambda *args: candidate_ids,
        )
        monkeypatch.setattr(
            "app.services.graph_service._db_query_mastery_map",
            lambda user_id, kp_ids: mastery_calls.append((user_id, list(kp_ids))) or {},
        )
        monkeypatch.setattr(
            "app.services.graph_service._db_query_chapter_ids",
            lambda kp_ids: ["ch_01"],
        )
        monkeypatch.setattr(
            "app.services.graph_service._db_load_graph_rows",
            lambda kp_ids: rows,
        )

        data = asyncio.run(
            get_student_graph("stu_a", view="network", max_nodes=80)
        )

        assert len(data.nodes) == data.meta.returned_nodes == 80
        assert data.meta.total_nodes == 502  # 500 KP + 1 章节 + 1 课程根节点
        assert data.meta.truncated is True
        assert len(mastery_calls) == 1
        assert len(mastery_calls[0][1]) == 80
        assert all(set(node.model_dump()) >= {"id", "node_type"} for node in data.nodes)

    def test_admin_graph_student_fields_are_null(self):
        """管理端 GraphData 不泄露任意学生状态字段。"""
        data = _build_graph_data(
            rows=_rows(2),
            selected_ids=["kp_000", "kp_001"],
            total_knowledge_points=2,
            max_nodes=20,
            view="network",
            focus_id=None,
            mastery_map={},
            is_student=False,
            total_chapters=1,
        )
        kp_nodes = [node for node in data.nodes if node.node_type == "knowledge_point"]
        assert kp_nodes
        assert all(node.mastery_probability is None for node in kp_nodes)
        assert all(node.status is None for node in kp_nodes)
        assert all(node.locked is None for node in kp_nodes)
        assert all(node.recommend_order is None for node in kp_nodes)

    def test_empty_graph_has_accurate_meta(self):
        """无知识点时返回真正的空图，而不是 code=0 的伪造根节点。"""
        data = _build_graph_data(
            rows={"knowledge_points": [], "chapters": [], "prerequisites": []},
            selected_ids=[],
            total_knowledge_points=0,
            max_nodes=80,
            view="tree",
            focus_id=None,
            mastery_map={},
            is_student=True,
            total_chapters=0,
        )
        assert data.nodes == []
        assert data.edges == []
        assert data.meta.total_nodes == data.meta.returned_nodes == 0
        assert data.meta.truncated is False

    def test_personalized_view_merges_mastery_and_recommendation(self):
        """个性化视图同时返回状态、推荐顺序和理由。"""
        data = _build_graph_data(
            rows=_rows(3),
            selected_ids=["kp_000", "kp_001", "kp_002"],
            total_knowledge_points=3,
            max_nodes=20,
            view="personalized",
            focus_id="kp_002",
            mastery_map={"kp_000": 0.2, "kp_001": 0.4},
            is_student=True,
            total_chapters=1,
        )
        kp_nodes = {node.id: node for node in data.nodes if node.node_type == "knowledge_point"}
        assert kp_nodes["kp_000"].status == "weak"
        assert kp_nodes["kp_000"].recommend_order is not None
        assert kp_nodes["kp_000"].reason
        assert kp_nodes["kp_002"].recommend_order is not None

    @pytest.mark.parametrize("max_nodes", [1, 2, 3])
    def test_focus_is_retained_when_it_is_last_candidate(self, monkeypatch, max_nodes):
        """focus 排在候选末尾时仍必须进入渲染窗口。"""
        focus_rows = {
            "knowledge_points": [
                {"id": "kp_a", "name": "A", "chapter_id": "ch_01", "difficulty": 0.2, "estimated_time": 10},
                {"id": "kp_b", "name": "B", "chapter_id": "ch_01", "difficulty": 0.2, "estimated_time": 10},
                {"id": "kp_focus", "name": "焦点", "chapter_id": "ch_01", "difficulty": 0.2, "estimated_time": 10},
            ],
            "chapters": [{"id": "ch_01", "name": "第一章"}],
            "prerequisites": [],
        }
        monkeypatch.setattr("app.services.graph_service._db_focus_exists", lambda *_: True)
        monkeypatch.setattr(
            "app.services.graph_service._db_query_candidate_ids",
            lambda *args: ["kp_a", "kp_b", "kp_focus"],
        )
        monkeypatch.setattr(
            "app.services.graph_service._db_load_graph_rows",
            lambda *_: focus_rows,
        )
        monkeypatch.setattr(
            "app.services.graph_service._db_query_chapter_ids",
            lambda *_: ["ch_01"],
        )
        monkeypatch.setattr(
            "app.services.graph_service._db_query_mastery_map",
            lambda *_: {},
        )

        data = asyncio.run(
            get_student_graph("stu_a", view="network", focus_id="kp_focus", max_nodes=max_nodes)
        )
        assert "kp_focus" in {node.id for node in data.nodes}
        assert data.meta.returned_nodes == len(data.nodes) <= max_nodes

    def test_focus_neighbors_use_distance_order_and_are_stable(self, monkeypatch):
        """邻居超过上限时保留 focus、近邻和稳定顺序。"""
        rows = {
            "knowledge_points": [
                {"id": "kp_focus", "name": "焦点", "difficulty": 0.2, "estimated_time": 10},
                {"id": "kp_near", "name": "近邻", "difficulty": 0.2, "estimated_time": 10},
                {"id": "kp_far", "name": "远邻", "difficulty": 0.2, "estimated_time": 10},
            ],
            "chapters": [],
            "prerequisites": [],
        }
        monkeypatch.setattr("app.services.graph_service._db_focus_exists", lambda *_: True)
        monkeypatch.setattr(
            "app.services.graph_service._db_query_candidate_ids",
            lambda *args: ["kp_focus", "kp_near", "kp_far"],
        )
        monkeypatch.setattr("app.services.graph_service._db_load_graph_rows", lambda *_: rows)
        monkeypatch.setattr("app.services.graph_service._db_query_mastery_map", lambda *_: {})
        monkeypatch.setattr("app.services.graph_service._db_query_chapter_ids", lambda *_: [])

        first = asyncio.run(
            get_student_neighbors("stu_a", "kp_focus", depth=2, max_nodes=3)
        )
        second = asyncio.run(
            get_student_neighbors("stu_a", "kp_focus", depth=2, max_nodes=3)
        )
        first_ids = [node.id for node in first.nodes]
        assert first_ids == ["course_root", "kp_focus", "kp_near"]
        assert first_ids == [node.id for node in second.nodes]
        assert "kp_far" not in first_ids

    def test_external_unrendered_prerequisite_locks_and_blocks_recommendation(self):
        """图外直接前置未掌握时，目标锁定且不被个性化推荐越过。"""
        rows = {
            "knowledge_points": [
                {"id": "kp_target", "name": "目标", "difficulty": 0.3, "estimated_time": 20},
            ],
            "external_knowledge_points": [
                {"id": "kp_external", "name": "图外前置", "difficulty": 0.1, "estimated_time": 10},
            ],
            "chapters": [],
            "prerequisites": [
                {"id": "pre_external_target", "source": "kp_external", "target": "kp_target"}
            ],
        }
        data = _build_graph_data(
            rows=rows,
            selected_ids=["kp_target"],
            total_knowledge_points=1,
            max_nodes=3,
            view="personalized",
            focus_id="kp_target",
            mastery_map={"kp_external": 0.2},
            is_student=True,
            total_chapters=0,
        )
        target = next(node for node in data.nodes if node.id == "kp_target")
        assert target.locked is True
        assert target.recommend_order is None

    @pytest.mark.parametrize(
        ("mastered_ids", "candidate_ids", "expected_ids"),
        [
            ({"kp_001", "kp_002"}, [], []),
            ({"kp_001"}, ["kp_002"], ["kp_002"]),
            (set(), ["kp_001", "kp_002"], ["kp_001", "kp_002"]),
        ],
    )
    def test_include_mastered_false_filters_in_neo4j_scope(
        self, monkeypatch, mastered_ids, candidate_ids, expected_ids
    ):
        """全掌握、部分掌握和无记录都在 DB 范围阶段准确处理。"""
        seen_excluded = []
        monkeypatch.setattr(
            "app.services.graph_service._db_query_mastered_ids",
            lambda *_: mastered_ids,
        )

        def select(*args):
            seen_excluded.append(args[5])
            return CandidateSelection(candidate_ids, len(candidate_ids), 0)

        monkeypatch.setattr("app.services.graph_service._db_query_candidate_ids", select)
        monkeypatch.setattr(
            "app.services.graph_service._db_load_graph_rows",
            lambda ids: {
                "knowledge_points": [
                    {"id": kp_id, "name": kp_id, "difficulty": 0.2, "estimated_time": 10}
                    for kp_id in ids
                ],
                "external_knowledge_points": [],
                "chapters": [],
                "prerequisites": [],
            },
        )
        monkeypatch.setattr("app.services.graph_service._db_query_mastery_map", lambda *_: {})

        data = asyncio.run(
            get_student_graph("stu_a", view="network", include_mastered=False, max_nodes=10)
        )
        actual_ids = [node.id for node in data.nodes if node.node_type == "knowledge_point"]
        assert actual_ids == expected_ids
        assert seen_excluded == [sorted(mastered_ids)]

    def test_two_students_do_not_share_mastery(self, monkeypatch):
        """相同图谱下两个学生的掌握度来自各自 user_id。"""
        rows = {
            "knowledge_points": [
                {"id": "kp_001", "name": "同一知识点", "difficulty": 0.2, "estimated_time": 10}
            ],
            "external_knowledge_points": [],
            "chapters": [],
            "prerequisites": [],
        }
        selection = CandidateSelection(["kp_001"], 1, 0)
        monkeypatch.setattr("app.services.graph_service._db_query_candidate_ids", lambda *args: selection)
        monkeypatch.setattr("app.services.graph_service._db_load_graph_rows", lambda *_: rows)
        monkeypatch.setattr(
            "app.services.graph_service._db_query_mastery_map",
            lambda user_id, *_: {"kp_001": 0.9 if user_id == "stu_a" else 0.2},
        )
        a = asyncio.run(get_student_graph("stu_a", view="tree"))
        b = asyncio.run(get_student_graph("stu_b", view="tree"))
        a_node = next(node for node in a.nodes if node.id == "kp_001")
        b_node = next(node for node in b.nodes if node.id == "kp_001")
        assert a_node.mastery_probability == 0.9
        assert b_node.mastery_probability == 0.2

    def test_large_mastery_scope_is_chunked_below_sql_parameter_limit(self, monkeypatch):
        """大图掌握度读取按有界批次执行，不触发 SQL Server 参数上限。"""
        calls = []

        class FakeCursor:
            def execute(self, query, params):
                calls.append((query, params))

            def fetchall(self):
                return []

        class FakeConnection:
            def cursor(self):
                return FakeCursor()

            def close(self):
                pass

        monkeypatch.setattr("app.db.sqlserver.get_connection", lambda: FakeConnection())
        result = _db_query_mastery_map("stu_a", [f"kp_{i}" for i in range(5000)])
        assert result == {}
        assert len(calls) == 6
        assert all(len(params) <= 901 for _, params in calls)

    def test_sql_failure_is_not_an_empty_success(self, monkeypatch):
        """SQL Server 异常必须向上标记为 GraphSqlServerError。"""
        monkeypatch.setattr(
            "app.services.graph_service._db_query_candidate_ids",
            lambda *args: ["kp_001"],
        )

        def boom(*args):
            raise RuntimeError("sql down")

        monkeypatch.setattr("app.services.graph_service._db_query_mastery_map", boom)
        monkeypatch.setattr(
            "app.services.graph_service._db_load_graph_rows",
            lambda kp_ids: _rows(1),
        )
        with pytest.raises(GraphSqlServerError):
            asyncio.run(get_student_graph("stu_a", view="tree"))

    def test_neo4j_failure_is_not_an_empty_success(self, monkeypatch):
        """Neo4j 异常必须向上标记为 GraphNeo4jError。"""
        def boom(*args):
            raise ServiceUnavailable("neo4j down")

        monkeypatch.setattr("app.services.graph_service._db_query_candidate_ids", boom)
        with pytest.raises(GraphNeo4jError):
            asyncio.run(get_student_graph("stu_a", view="tree"))

    def test_cycle_is_not_returned_as_a_successful_graph(self):
        """个性化推荐遇到环路时由 service 标记为图谱错误。"""
        rows = {
            "knowledge_points": [
                {"id": "kp_a", "name": "A", "difficulty": 0.2, "estimated_time": 10},
                {"id": "kp_b", "name": "B", "difficulty": 0.2, "estimated_time": 10},
            ],
            "chapters": [],
            "prerequisites": [
                {"id": "pre_a_b", "source": "kp_a", "target": "kp_b"},
                {"id": "pre_b_a", "source": "kp_b", "target": "kp_a"},
            ],
        }
        with pytest.raises(KnowledgeGraphCycleError):
            _build_graph_data(
                rows=rows,
                selected_ids=["kp_a", "kp_b"],
                total_knowledge_points=2,
                max_nodes=20,
                view="personalized",
                focus_id=None,
                mastery_map={},
                is_student=True,
                total_chapters=0,
            )

    @pytest.mark.parametrize("view", ["tree", "network", "personalized"])
    def test_cycle_crossing_render_window_is_not_success(self, monkeypatch, view):
        """选中 A、窗口外 B 且 A→B→A 时，三种视图都返回图数据库错误。"""
        selection = CandidateSelection(["kp_a"], 2, 0)
        rows = {
            "knowledge_points": [
                {"id": "kp_a", "name": "A", "difficulty": 0.2, "estimated_time": 10},
            ],
            "external_knowledge_points": [
                {"id": "kp_b", "name": "B", "difficulty": 0.2, "estimated_time": 10},
            ],
            "chapters": [],
            "prerequisites": [
                {"id": "pre_a_b", "source": "kp_a", "target": "kp_b"},
                {"id": "pre_b_a", "source": "kp_b", "target": "kp_a"},
            ],
            "cycle_path": ["kp_a", "kp_b", "kp_a"],
        }
        monkeypatch.setattr(
            "app.services.graph_service._db_query_candidate_ids",
            lambda *args: selection,
        )
        monkeypatch.setattr(
            "app.services.graph_service._db_load_graph_rows",
            lambda *_: rows,
        )

        with pytest.raises(GraphNeo4jError):
            asyncio.run(get_student_graph("stu_a", view=view, max_nodes=1))

    def test_cycle_entirely_inside_render_window_is_not_success(self, monkeypatch):
        """环完全位于渲染窗口内时，仍不能返回成功图。"""
        monkeypatch.setattr(
            "app.services.graph_service._db_query_candidate_ids",
            lambda *args: CandidateSelection(["kp_a", "kp_b"], 2, 0),
        )
        monkeypatch.setattr(
            "app.services.graph_service._db_load_graph_rows",
            lambda *_: {
                "knowledge_points": [
                    {"id": "kp_a", "name": "A", "difficulty": 0.2, "estimated_time": 10},
                    {"id": "kp_b", "name": "B", "difficulty": 0.2, "estimated_time": 10},
                ],
                "external_knowledge_points": [],
                "chapters": [],
                "prerequisites": [],
                "cycle_path": ["kp_a", "kp_b", "kp_a"],
            },
        )

        with pytest.raises(GraphNeo4jError):
            asyncio.run(get_student_graph("stu_a", view="tree", max_nodes=2))

    def test_cycle_query_returns_only_path_ids_without_per_node_queries(self, monkeypatch):
        """环检测只执行一次 ID 路径查询，不按节点读取属性。"""
        calls = []

        graph_record = {
            "knowledge_points": [
                {"id": "kp_a", "name": "A", "chapter_id": None, "difficulty": 0.2, "estimated_time": 10}
            ],
            "external_knowledge_points": [],
            "chapters": [],
            "prerequisites": [],
        }

        class FakeResult:
            def __init__(self, record):
                self.record = record

            def single(self):
                return self.record

        class FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def run(self, query, **params):
                calls.append((query, params))
                if "MATCH cycle=" in query:
                    return FakeResult({"cycle_path": []})
                return FakeResult(graph_record)

        class FakeDriver:
            def session(self):
                return FakeSession()

        monkeypatch.setattr("app.services.graph_service.get_driver", lambda: FakeDriver())
        rows = _db_load_graph_rows(["kp_a"])

        assert rows["cycle_path"] == []
        assert len(calls) == 2
        cycle_query = next(query for query, _ in calls if "MATCH cycle=" in query)
        assert "RETURN [node IN nodes(cycle) | node.id] AS cycle_path" in cycle_query
        assert "name" not in cycle_query
        assert all(params["node_ids"] == ["kp_a"] for _, params in calls)


class TestGraphRoutes:
    """三条接口的认证、参数和错误映射。"""

    @pytest.fixture
    def client(self):
        app.dependency_overrides[require_student] = lambda: STUDENT
        yield TestClient(app)
        app.dependency_overrides.pop(require_student, None)

    def test_student_graph_requires_student_token(self):
        """无 Token 的个性化图谱返回 401，不降级匿名。"""
        response = TestClient(app).get("/api/student/graph")
        assert response.status_code == 401
        assert response.json()["code"] == 40100

    def test_admin_graph_requires_admin_token(self):
        """管理图谱无 Token 返回 401。"""
        response = TestClient(app).get("/api/admin/graph")
        assert response.status_code == 401
        assert response.json()["code"] == 40100

    def test_student_graph_returns_unified_data(self, client, monkeypatch):
        data = GraphData(
            nodes=[],
            edges=[],
            meta={"view": "personalized", "total_nodes": 0, "returned_nodes": 0},
        )
        async def fake_graph(**kwargs):
            return data

        monkeypatch.setattr("app.routers.student.graph.get_student_graph", fake_graph)
        response = client.get("/api/student/graph", params={"view": "personalized"})
        assert response.status_code == 200
        assert response.json()["code"] == 0
        assert set(response.json()["data"]) == {"nodes", "edges", "meta"}

    def test_neighbor_direction_and_focus_error(self, client, monkeypatch):
        calls = []

        async def fake_neighbors(**kwargs):
            calls.append(kwargs)
            raise GraphFocusNotFoundError(kwargs["focus_id"])

        monkeypatch.setattr("app.routers.student.graph.get_student_neighbors", fake_neighbors)
        response = client.get(
            "/api/student/graph/kp_999/neighbors",
            params={"direction": "incoming", "depth": 2, "max_nodes": 10},
        )
        assert response.status_code == 200
        assert response.json()["code"] == 40400
        assert calls[0]["direction"] == "incoming"

    def test_invalid_graph_parameters_use_40000(self, client):
        response = client.get("/api/student/graph", params={"depth": 4})
        assert response.status_code == 422
        assert response.json()["code"] == 40000
