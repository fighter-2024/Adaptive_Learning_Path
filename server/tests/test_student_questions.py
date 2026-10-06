"""正式学生取题接口测试。

覆盖路由注册、学生鉴权、Q 矩阵/已作答筛选和响应脱敏；不依赖真实数据库。
"""

import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.auth import UserInfo
from app.models.question import QuestionOption
from app.models.student_question import (
    StudentQuestionItem,
    StudentQuestionList,
    StudentQuestionQuery,
)
from app.routers.dependencies import get_current_user, require_student
from app.services.student_question_service import (
    StudentQuestionKnowledgePointNotFoundError,
    _db_list_student_questions,
    list_student_questions,
)


class TestStudentQuestionModels:
    """学生题目模型不能携带管理端答案字段。"""

    def test_query_contract(self):
        query = StudentQuestionQuery(
            knowledge_point_id="kp_001",
            count=5,
            exclude_done=True,
            type="multi_choice",
        )
        assert query.model_dump() == {
            "knowledge_point_id": "kp_001",
            "count": 5,
            "exclude_done": True,
            "type": "multi_choice",
        }
        with pytest.raises(ValidationError):
            StudentQuestionQuery(knowledge_point_id="kp_001", count=0)
        with pytest.raises(ValidationError):
            StudentQuestionQuery(knowledge_point_id="kp_001", type="essay")

    def test_response_has_only_student_fields(self):
        item = StudentQuestionItem(
            id="q_001",
            content="题干",
            type="single_choice",
            difficulty=0.3,
            options=[QuestionOption(label="A", content="选项 A")],
        )
        dumped = StudentQuestionList(list=[item], total=1).model_dump()
        assert set(dumped["list"][0]) == {
            "id",
            "content",
            "type",
            "difficulty",
            "options",
        }
        assert "answer" not in dumped["list"][0]
        assert "explanation" not in dumped["list"][0]


class TestStudentQuestionService:
    """服务层编排与 SQL 筛选测试。"""

    def test_list_checks_kp_and_maps_safe_fields(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.student_question_service._db_knowledge_point_exists",
            lambda kp_id: True,
        )
        monkeypatch.setattr(
            "app.services.student_question_service._db_list_student_questions",
            lambda *args: (
                [
                    {
                        "id": "q_001",
                        "content": "题干",
                        "type": "single_choice",
                        "difficulty": 0.3,
                        "options": [{"label": "A", "content": "选项 A"}],
                    }
                ],
                1,
            ),
        )
        result = asyncio.run(
            list_student_questions("kp_001", "stu_001", 10, False, None)
        )
        assert result.total == 1
        assert result.list[0].options[0].label == "A"
        assert "answer" not in result.list[0].model_dump()

    def test_missing_kp_is_rejected_before_sql(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.student_question_service._db_knowledge_point_exists",
            lambda kp_id: False,
        )
        with pytest.raises(StudentQuestionKnowledgePointNotFoundError):
            asyncio.run(
                list_student_questions("kp_missing", "stu_001", 10, False, None)
            )

    def test_sql_filters_type_and_done_questions(self, monkeypatch):
        class FakeCursor:
            def __init__(self):
                self.calls = []

            def execute(self, sql, params=()):
                self.calls.append((sql, params))
                return self

            def fetchone(self):
                return (1,)

            def fetchall(self):
                return [
                    (
                        "q_001",
                        "题干",
                        "single_choice",
                        0.3,
                        '[{"label":"A","content":"选项 A"}]',
                    )
                ]

        class FakeConnection:
            def __init__(self):
                self.cursor_instance = FakeCursor()

            def cursor(self):
                return self.cursor_instance

            def close(self):
                pass

        connection = FakeConnection()
        monkeypatch.setattr(
            "app.services.student_question_service.get_connection",
            lambda: connection,
        )
        rows, total = _db_list_student_questions(
            "kp_001", "stu_001", 5, True, "single_choice"
        )
        assert total == 1
        assert rows[0]["options"][0]["label"] == "A"
        count_sql, count_params = connection.cursor_instance.calls[0]
        select_sql, select_params = connection.cursor_instance.calls[1]
        assert "q.type = ?" in count_sql
        assert "NOT EXISTS" in count_sql
        assert count_params == ("kp_001", "single_choice", "stu_001")
        assert select_params[-1] == 5
        assert "answer_records" in select_sql


class TestStudentQuestionRoutes:
    """路由鉴权与统一响应。"""

    def test_requires_student_token(self):
        response = TestClient(app).get(
            "/api/student/questions?knowledge_point_id=kp_001"
        )
        assert response.status_code == 401
        assert response.json()["code"] == 40100

    def test_admin_token_is_forbidden(self):
        app.dependency_overrides[get_current_user] = lambda: UserInfo(
            user_id="adm_001",
            username="admin",
            name="管理员",
            role="admin",
        )
        try:
            response = TestClient(app).get(
                "/api/student/questions?knowledge_point_id=kp_001"
            )
        finally:
            app.dependency_overrides.pop(get_current_user, None)
        assert response.status_code == 403
        assert response.json()["code"] == 40101

    def test_student_response_is_declassified(self, monkeypatch):
        app.dependency_overrides[require_student] = lambda: UserInfo(
            user_id="stu_001",
            username="student",
            name="学生",
            role="student",
        )
        async def fake_list_student_questions(**kwargs):
            return StudentQuestionList(
                list=[
                    StudentQuestionItem(
                        id="q_001",
                        content="题干",
                        type="single_choice",
                        difficulty=0.3,
                        options=[{"label": "A", "content": "选项 A"}],
                    )
                ],
                total=1,
            )

        monkeypatch.setattr(
            "app.routers.student.questions.list_student_questions",
            fake_list_student_questions,
        )
        try:
            response = TestClient(app).get(
                "/api/student/questions?knowledge_point_id=kp_001&count=1"
            )
        finally:
            app.dependency_overrides.pop(require_student, None)
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert body["data"]["list"][0]["options"]
        assert "answer" not in body["data"]["list"][0]
        assert "explanation" not in body["data"]["list"][0]
