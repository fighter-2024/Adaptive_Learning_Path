"""管理端图谱读取接口与裁剪逻辑测试。"""

from fastapi.testclient import TestClient

from app.main import app
from app.models.auth import UserInfo
from app.routers.dependencies import require_admin
from app.services.graph_service import _build_graph_data


def test_build_graph_data_contains_real_topology_fields():
    """图谱 service 组装统一节点、边和截断元数据。"""
    data = _build_graph_data(
        rows={
            "knowledge_points": [
                {"id": "kp_001", "name": "一元一次方程", "chapter_id": "ch_01", "difficulty": 0.2, "estimated_time": 20},
                {"id": "kp_002", "name": "因式分解", "chapter_id": "ch_01", "difficulty": 0.4, "estimated_time": 30},
            ],
            "chapters": [{"id": "ch_01", "name": "方程"}],
            "prerequisites": [{"id": "pre_kp_001_kp_002", "source": "kp_001", "target": "kp_002"}],
        },
        selected_ids=["kp_001", "kp_002"],
        total_knowledge_points=2,
        max_nodes=10,
        view="network",
        focus_id="kp_002",
        mastery_map={},
        is_student=False,
        total_chapters=1,
    )

    assert {node.id for node in data.nodes} >= {"course_root", "ch_01", "kp_001", "kp_002"}
    assert {edge.id for edge in data.edges} >= {"pre_kp_001_kp_002"}
    assert data.meta.focus_id == "kp_002"
    assert data.meta.returned_nodes == len(data.nodes)


def test_admin_graph_route_returns_unified_graph_data(monkeypatch):
    """管理图谱路由要求管理员身份且返回统一 GraphData。"""
    from app.models.graph import GraphData, GraphMeta, GraphNode

    async def fake_graph(**_kwargs):
        return GraphData(
            nodes=[GraphNode(id="kp_001", label="测试", node_type="knowledge_point")],
            edges=[],
            meta=GraphMeta(view="network", total_nodes=1, returned_nodes=1),
        )

    monkeypatch.setattr("app.routers.admin.graph.get_admin_graph", fake_graph)
    app.dependency_overrides[require_admin] = lambda: UserInfo(
        user_id="adm_test", username="admin", name="管理员", role="admin"
    )
    try:
        response = TestClient(app).get("/api/admin/graph", params={"depth": 2})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"code", "data", "message"}
    assert body["code"] == 0
    assert body["data"]["nodes"][0]["id"] == "kp_001"
