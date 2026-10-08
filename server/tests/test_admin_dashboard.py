"""M6 管理端仪表盘与学生数据看板接口测试。"""

from fastapi.testclient import TestClient

from app.main import app
from app.models import ApiResponse, DashboardSummary, StudentDetail
from app.models.auth import UserInfo
from app.routers.dependencies import get_current_user, require_admin


def _admin() -> UserInfo:
    """返回测试管理员身份。"""
    return UserInfo(user_id="adm_test", username="admin", name="管理员", role="admin")


def _student() -> UserInfo:
    """返回测试学生身份。"""
    return UserInfo(user_id="stu_test", username="student", name="学生", role="student")


def test_admin_dashboard_requires_admin_token():
    """未登录访问 M6 管理接口必须返回 401。"""
    response = TestClient(app).get("/api/admin/dashboard/summary")
    assert response.status_code == 401
    assert response.json()["code"] == 40100


def test_student_token_cannot_access_admin_dashboard():
    """学生身份访问管理端仪表盘必须返回 403。"""
    app.dependency_overrides[get_current_user] = _student
    try:
        response = TestClient(app).get("/api/admin/dashboard/summary")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 403
    assert response.json()["code"] == 40101


def test_admin_dashboard_summary_returns_real_contract_shape(monkeypatch):
    """管理员可读取统一响应格式的仪表盘摘要。"""
    async def fake_summary():
        return DashboardSummary(
            student_count=2,
            question_count=12,
            knowledge_point_count=22,
            weekly_active_students=1,
            recent_diagnoses=[],
        )

    monkeypatch.setattr(
        "app.routers.admin.dashboard.get_dashboard_summary", fake_summary
    )
    app.dependency_overrides[require_admin] = _admin
    try:
        response = TestClient(app).get("/api/admin/dashboard/summary")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert response.json()["data"] == {
        "student_count": 2,
        "question_count": 12,
        "knowledge_point_count": 22,
        "weekly_active_students": 1,
        "recent_diagnoses": [],
    }


def test_admin_student_detail_route_keeps_student_scope(monkeypatch):
    """详情路由把目标学生 ID 交给 service，且不会把学生 Token 当管理员。"""
    requested_ids = []

    async def fake_detail(student_id):
        requested_ids.append(student_id)
        return StudentDetail(
            student_id=student_id,
            username="zhangsan",
            name="张三",
            meta={
                "answer_history_limit": 50,
                "diagnosis_history_limit": 10,
                "learning_history_total": 0,
                "knowledge_point_source": "test",
            },
        )

    monkeypatch.setattr(
        "app.routers.admin.students.get_student_detail", fake_detail
    )
    app.dependency_overrides[require_admin] = _admin
    try:
        response = TestClient(app).get("/api/admin/students/stu_001")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["data"]["student_id"] == "stu_001"
    assert requested_ids == ["stu_001"]


def test_admin_student_list_pagination_uses_uniform_response(monkeypatch):
    """学生列表接口返回统一分页字段。"""
    async def fake_list_students(page, page_size, keyword):
        assert (page, page_size, keyword) == (2, 10, "张三")
        return [], 11

    monkeypatch.setattr("app.routers.admin.students.list_students", fake_list_students)
    app.dependency_overrides[require_admin] = _admin
    try:
        response = TestClient(app).get(
            "/api/admin/students",
            params={"page": 2, "page_size": 10, "keyword": " 张三 "},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["data"] == {
        "list": [],
        "total": 11,
        "page": 2,
        "page_size": 10,
    }
