"""M5-R1：管理端知识图谱与题库返修的最小回归测试。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.auth import UserInfo
from app.models.knowledge_point import KnowledgePointCreateRequest, KnowledgePointItem
from app.routers.dependencies import require_admin
from app.services import knowledge_point_service as service


class _Result:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def single(self):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


class _Tx:
    def __init__(self, *, edges=None, found_ids=None, fail_on_prerequisite_create=False):
        self.edges = list(edges or [])
        self.found_ids = list(found_ids or [])
        self.fail_on_prerequisite_create = fail_on_prerequisite_create
        self.queries = []

    def run(self, query, **params):
        normalized = " ".join(query.split())
        self.queries.append((normalized, params))
        if "RETURN c.name AS chapter_name" in normalized:
            return _Result([{"chapter_name": "第一章"}])
        if "RETURN k.id AS id" in normalized:
            return _Result([{"id": "kp_target"}])
        if "RETURN c.name AS name" in normalized:
            return _Result([{"name": "第一章"}])
        if "RETURN collect(p.id) AS ids" in normalized:
            return _Result([{"ids": self.found_ids}])
        if "RETURN source.id AS source" in normalized:
            return _Result(self.edges)
        if "RETURN c.name AS chapter_name," in normalized:
            return _Result([{"chapter_name": "第一章", "created_at": "2026-10-04T00:00:00", "prerequisite_count": 1}])
        if "CREATE (pre)" in normalized and self.fail_on_prerequisite_create:
            raise RuntimeError("模拟前置关系写入失败")
        return _Result()


class _Session:
    def __init__(self, tx):
        self.tx = tx
        self.execute_write_calls = 0
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute_write(self, callback):
        self.execute_write_calls += 1
        try:
            return callback(self.tx)
        except Exception:
            self.rolled_back = True
            raise


class _Driver:
    def __init__(self, session):
        self.session_instance = session

    def session(self):
        return self.session_instance


def test_create_knowledge_point_request_accepts_atomic_prerequisites():
    request = KnowledgePointCreateRequest(
        name="因式分解",
        chapter_id="ch_01",
        difficulty=0.4,
        estimated_time=30,
        prerequisite_ids=["kp_001", "kp_001"],
    )
    assert request.prerequisite_ids == ["kp_001", "kp_001"]


def test_db_create_writes_node_and_prerequisites_in_one_transaction(monkeypatch):
    tx = _Tx(found_ids=["kp_001"])
    session = _Session(tx)
    monkeypatch.setattr(service, "get_driver", lambda: _Driver(session))

    item = service._db_create(
        "kp_new", "因式分解", "", "ch_01", 0.4, 30, ["kp_001"]
    )

    assert session.execute_write_calls == 1
    assert item["prerequisite_count"] == 1
    assert any("CREATE (pre)" in query for query, _ in tx.queries)


def test_db_update_cycle_is_rejected_before_node_or_relation_writes(monkeypatch):
    tx = _Tx(
        found_ids=["kp_001"],
        edges=[{"source": "kp_target", "target": "kp_001"}],
    )
    session = _Session(tx)
    monkeypatch.setattr(service, "get_driver", lambda: _Driver(session))

    with pytest.raises(service.PrerequisiteValidationError, match="前置关系存在环"):
        service._db_update(
            "kp_target", "更新后名称", "", "ch_01", 0.5, 40, ["kp_001"]
        )

    assert session.execute_write_calls == 1
    assert session.rolled_back is True
    assert not any("SET k.name" in query or "DELETE r" in query for query, _ in tx.queries)


def test_db_update_relation_failure_rolls_back_same_transaction(monkeypatch):
    tx = _Tx(found_ids=["kp_001"], fail_on_prerequisite_create=True)
    session = _Session(tx)
    monkeypatch.setattr(service, "get_driver", lambda: _Driver(session))

    with pytest.raises(RuntimeError, match="模拟前置关系写入失败"):
        service._db_update(
            "kp_target", "更新后名称", "", "ch_01", 0.5, 40, ["kp_001"]
        )

    assert session.execute_write_calls == 1
    assert session.rolled_back is True
    assert any("SET k.name" in query for query, _ in tx.queries)
    assert any("CREATE (pre)" in query for query, _ in tx.queries)


def test_admin_create_route_forwards_prerequisite_ids(monkeypatch):
    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return KnowledgePointItem(
            id="kp_new",
            name=kwargs["name"],
            description=kwargs["description"],
            chapter_id=kwargs["chapter_id"],
            chapter_name="第一章",
            difficulty=kwargs["difficulty"],
            estimated_time=kwargs["estimated_time"],
            prerequisite_count=len(kwargs["prerequisite_ids"]),
            question_count=0,
            created_at="2026-10-04T00:00:00",
        )

    monkeypatch.setattr("app.routers.admin.knowledge_points.create_knowledge_point", fake_create)
    app.dependency_overrides[require_admin] = lambda: UserInfo(
        user_id="adm_test", username="admin", name="管理员", role="admin"
    )
    try:
        response = TestClient(app).post(
            "/api/admin/knowledge-points",
            json={
                "name": "因式分解",
                "description": "",
                "chapter_id": "ch_01",
                "difficulty": 0.4,
                "estimated_time": 30,
                "prerequisite_ids": ["kp_001"],
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["data"]["prerequisite_count"] == 1
    assert captured["prerequisite_ids"] == ["kp_001"]
