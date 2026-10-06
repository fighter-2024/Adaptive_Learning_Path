"""
题库管理模块单元测试

测试覆盖（不依赖真实 SQL Server / Neo4j，可在任何环境运行）：
- Pydantic 请求/响应模型校验（含选项-答案一致性、判断题默认选项）
- ID 生成、选项 JSON 序列化等纯函数逻辑
- 批量导入逐行校验与成功/失败统计（mock 数据库）
- 路由注册正确性与统一响应格式（mock 数据库连接）
"""

import asyncio
import re

import pytest
from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable
from pydantic import ValidationError

from app.main import app
from app.models.auth import UserInfo
from app.models.question import (
    QuestionBatchImportRequest,
    QuestionCreateRequest,
    QuestionDetail,
    QuestionListItem,
    QuestionListQuery,
)
from app.routers.dependencies import get_current_user, require_admin
from app.services.question_service import (
    _db_list_page,
    _generate_question_id,
    batch_import_questions,
    first_validation_message,
    json_to_options,
    list_questions,
    options_to_json,
)


def make_valid_body(**overrides) -> dict:
    """构造一个合法的单选题请求体（供测试复用）"""
    body = {
        "content": "下列哪个是方程 x²-4=0 的解？",
        "type": "single_choice",
        "difficulty": 0.3,
        "options": [
            {"label": "A", "content": "x=4"},
            {"label": "B", "content": "x=2"},
            {"label": "C", "content": "x=0"},
            {"label": "D", "content": "x=-4"},
        ],
        "answer": "B",
        "explanation": "x²-4=0 → x=±2",
        "knowledge_point_ids": ["kp_001"],
    }
    body.update(overrides)
    return body


class TestQuestionModels:
    """Pydantic 模型校验"""

    def test_valid_single_choice(self):
        """正常单选题请求"""
        req = QuestionCreateRequest(**make_valid_body())
        assert req.type == "single_choice"
        assert len(req.options) == 4
        assert req.answer == "B"

    def test_valid_multi_choice_normalized(self):
        """多选题答案支持 "A, C" 写法并规范化为 "A,C"（按选项顺序）"""
        req = QuestionCreateRequest(
            **make_valid_body(type="multi_choice", answer="C, A")
        )
        assert req.answer == "A,C"

    def test_multi_choice_answer_with_spaces(self):
        """多选答案允许空格分隔"""
        req = QuestionCreateRequest(**make_valid_body(type="multi_choice", answer=" A , D "))
        assert req.answer == "A,D"

    def test_multi_choice_duplicate_answer_rejected(self):
        """多选答案重复"""
        with pytest.raises(ValidationError):
            QuestionCreateRequest(**make_valid_body(type="multi_choice", answer="A,A"))

    def test_answer_not_in_options_rejected(self):
        """答案必须是选项之一（单选/多选）"""
        with pytest.raises(ValidationError):
            QuestionCreateRequest(**make_valid_body(answer="E"))
        with pytest.raises(ValidationError):
            QuestionCreateRequest(**make_valid_body(type="multi_choice", answer="A,E"))

    def test_options_required_for_choice(self):
        """选择题选项不能为空"""
        body = make_valid_body()
        body.pop("options")
        with pytest.raises(ValidationError) as exc_info:
            QuestionCreateRequest(**body)
        assert "选项不能为空" in str(exc_info.value)

    def test_options_at_least_two(self):
        """选择题选项至少 2 个"""
        with pytest.raises(ValidationError):
            QuestionCreateRequest(
                **make_valid_body(options=[{"label": "A", "content": "x=2"}])
            )

    def test_duplicate_labels_rejected(self):
        """选项标识不能重复"""
        with pytest.raises(ValidationError):
            QuestionCreateRequest(
                **make_valid_body(
                    options=[
                        {"label": "A", "content": "x=2"},
                        {"label": "A", "content": "x=4"},
                    ]
                )
            )

    def test_true_false_default_options(self):
        """判断题答案 true/false；选项缺省时补默认「对/错」"""
        body = make_valid_body(type="true_false", answer="true")
        body.pop("options")
        req = QuestionCreateRequest(**body)
        assert req.answer == "true"
        assert [opt.label for opt in req.options] == ["对", "错"]

    def test_true_false_invalid_answer(self):
        """判断题答案只能是 true 或 false"""
        with pytest.raises(ValidationError):
            QuestionCreateRequest(**make_valid_body(type="true_false", answer="A"))

    def test_difficulty_range(self):
        """难度必须 0~1"""
        with pytest.raises(ValidationError):
            QuestionCreateRequest(**make_valid_body(difficulty=1.5))
        with pytest.raises(ValidationError):
            QuestionCreateRequest(**make_valid_body(difficulty=-0.1))

    def test_knowledge_point_ids_required(self):
        """关联知识点至少 1 个（DINA 约束）"""
        with pytest.raises(ValidationError):
            QuestionCreateRequest(**make_valid_body(knowledge_point_ids=[]))

    def test_knowledge_point_ids_deduped(self):
        """知识点 ID 去重（q_matrix 唯一约束）"""
        req = QuestionCreateRequest(
            **make_valid_body(knowledge_point_ids=["kp_001", "kp_002", "kp_001"])
        )
        assert req.knowledge_point_ids == ["kp_001", "kp_002"]

    def test_content_required(self):
        """题干必填"""
        with pytest.raises(ValidationError):
            QuestionCreateRequest(**make_valid_body(content=""))

    def test_list_item_model_fields(self):
        """列表项模型字段与 API 契约一致"""
        item = QuestionListItem(
            id="q_001",
            content="下列哪个是方程 x²-4=0 的解？",
            type="single_choice",
            difficulty=0.3,
            knowledge_point_ids=["kp_001"],
            knowledge_point_names=["一元二次方程的定义"],
            created_at="2026-01-15T10:00:00",
        )
        dumped = item.model_dump()
        for field in (
            "id", "content", "type", "difficulty",
            "knowledge_point_ids", "knowledge_point_names", "created_at",
        ):
            assert field in dumped

    def test_detail_model_fields(self):
        """详情模型字段与 API 契约一致（含 options/answer/explanation）"""
        detail = QuestionDetail(
            id="q_001",
            content="下列哪个是方程 x²-4=0 的解？",
            type="single_choice",
            difficulty=0.3,
            options=[{"label": "A", "content": "x=4"}, {"label": "B", "content": "x=2"}],
            answer="B",
            explanation="x²-4=0 → x=±2",
            knowledge_point_ids=["kp_001"],
            created_at="2026-01-15T10:00:00",
        )
        dumped = detail.model_dump()
        assert dumped["options"][0]["label"] == "A"
        assert dumped["answer"] == "B"
        assert dumped["explanation"] == "x²-4=0 → x=±2"

    def test_batch_request_empty_rejected(self):
        """批量导入 questions 不能为空"""
        with pytest.raises(ValidationError):
            QuestionBatchImportRequest(questions=[])


class TestQuestionListQuery:
    """GET /questions 查询参数模型（含难度区间交叉校验）"""

    def test_valid_range(self):
        """难度区间参数合法（可单独使用下限或上限）"""
        assert QuestionListQuery(difficulty_min=0.2, difficulty_max=0.8).difficulty_min == 0.2
        assert QuestionListQuery(difficulty_min=0.2).difficulty_max is None
        assert QuestionListQuery(difficulty_max=0.8).difficulty_min is None
        assert QuestionListQuery().difficulty_min is None

    def test_min_greater_than_max_rejected(self):
        """难度下限不能大于上限"""
        with pytest.raises(ValidationError) as exc_info:
            QuestionListQuery(difficulty_min=0.8, difficulty_max=0.2)
        assert "difficulty_min" in str(exc_info.value)

    def test_range_out_of_bounds_rejected(self):
        """难度区间必须在 0~1 内"""
        with pytest.raises(ValidationError):
            QuestionListQuery(difficulty_min=1.5)
        with pytest.raises(ValidationError):
            QuestionListQuery(difficulty_max=-0.1)

    def test_invalid_type_rejected(self):
        """题型枚举外取值校验失败"""
        with pytest.raises(ValidationError):
            QuestionListQuery(type="essay")


class TestQuestionIDGeneration:
    """业务 ID 生成"""

    def test_id_prefix(self):
        """ID 以 q_ 开头"""
        assert _generate_question_id().startswith("q_")

    def test_id_format(self):
        """ID 格式: q_xxxxxxxx (8 位十六进制)"""
        assert re.match(r"^q_[0-9a-f]{8}$", _generate_question_id()) is not None

    def test_id_unique(self):
        """每次生成不同 ID"""
        ids = {_generate_question_id() for _ in range(100)}
        assert len(ids) == 100


class TestOptionsJson:
    """选项 JSON 序列化（存储层 NVARCHAR(MAX) 列）"""

    def test_roundtrip(self):
        """序列化再解析保持数据一致（含中文）"""
        options = [{"label": "A", "content": "x=2"}, {"label": "B", "content": "x=4"}]
        assert json_to_options(options_to_json(options)) == options

    def test_ensure_ascii_false(self):
        """JSON 保留中文原文（ensure_ascii=False）"""
        raw = options_to_json([{"label": "对", "content": "正确"}])
        assert "对" in raw and "正确" in raw

    def test_empty_and_invalid(self):
        """空值/非法 JSON 返回空列表，不抛异常"""
        assert json_to_options(None) == []
        assert json_to_options("") == []
        assert json_to_options("not-a-json") == []
        assert json_to_options('{"not": "a list"}') == []


class TestFirstValidationMessage:
    """批量导入错误信息提取"""

    def test_strips_value_error_prefix(self):
        """业务校验中文提示去掉 Pydantic 前缀"""
        body = make_valid_body()
        body.pop("options")
        with pytest.raises(ValidationError) as exc_info:
            QuestionCreateRequest(**body)
        assert first_validation_message(exc_info.value) == "选项不能为空"

    def test_field_constraint_message(self):
        """字段约束（如难度范围）返回约束文案（不抛内部异常）"""
        with pytest.raises(ValidationError) as exc_info:
            QuestionCreateRequest(**make_valid_body(difficulty=1.5))
        message = first_validation_message(exc_info.value)
        assert "1" in message


class TestBatchImport:
    """批量导入逐行校验与成功/失败统计（mock Neo4j 存在性查询与 SQL Server 写入）"""

    @staticmethod
    def _run(coro):
        return asyncio.run(coro)

    def test_partial_success(self, monkeypatch):
        """合法行导入成功；校验失败/知识点缺失行记入 errors，不阻塞其他行"""
        monkeypatch.setattr(
            "app.services.question_service._db_check_kp_exist",
            lambda ids: {"kp_001"},
        )
        created = []

        def fake_create(question_id, *args, **kwargs):
            created.append(question_id)

        monkeypatch.setattr(
            "app.services.question_service._db_create_question", fake_create
        )

        valid = make_valid_body()
        missing_kp = make_valid_body(knowledge_point_ids=["kp_999"])
        no_options = make_valid_body()
        no_options.pop("options")

        result = self._run(batch_import_questions([valid, missing_kp, no_options]))
        assert result.success_count == 1
        assert result.fail_count == 2
        assert len(created) == 1
        assert [e.row for e in result.errors] == [2, 3]
        assert result.errors[0].message == "关联知识点不存在: kp_999"
        assert result.errors[1].message == "选项不能为空"

    def test_all_fail(self, monkeypatch):
        """全部失败时 success_count=0，errors 与行数一致"""
        monkeypatch.setattr(
            "app.services.question_service._db_check_kp_exist", lambda ids: set()
        )
        monkeypatch.setattr(
            "app.services.question_service._db_create_question",
            lambda *a, **kw: None,
        )
        rows = [make_valid_body(), make_valid_body()]
        result = self._run(batch_import_questions(rows))
        assert result.success_count == 0
        assert result.fail_count == 2

    def test_invalid_rows_rejected_before_write(self, monkeypatch):
        """非法行不写入数据库；知识点存在性一次性批量查询（单次 Neo4j 查询）"""
        seen = []

        def fake_check(ids):
            seen.append(list(ids))
            return set(ids)

        monkeypatch.setattr(
            "app.services.question_service._db_check_kp_exist", fake_check
        )
        monkeypatch.setattr(
            "app.services.question_service._db_create_question",
            lambda *a, **kw: None,
        )
        valid = make_valid_body(knowledge_point_ids=["kp_001"])
        bad = make_valid_body(knowledge_point_ids=["kp_002"])
        bad.pop("options")
        result = self._run(batch_import_questions([valid, bad]))
        assert result.success_count == 1
        assert result.fail_count == 1
        assert seen == [["kp_001", "kp_002"]]  # 单次查询覆盖全部行涉及的知识点


class TestListSQLAssembly:
    """列表查询 SQL 拼装（mock pyodbc 连接，验证难度区间为闭区间参数化筛选）"""

    class _FakeCursor:
        """记录执行过的 SQL 与参数，返回固定行"""

        def __init__(self):
            self.executed = []

        def execute(self, sql, params=None):
            self.executed.append((sql, params))

        def fetchone(self):
            return (7,)

        def fetchall(self):
            return []

    class _FakeConn:
        def __init__(self):
            self._cursor = TestListSQLAssembly._FakeCursor()

        def cursor(self):
            return self._cursor

        def close(self):
            pass

    def test_difficulty_range_builds_closed_interval(self, monkeypatch):
        """难度区间拼出 difficulty >= ? 与 difficulty <= ?（含边界，参数化）"""
        fake = self._FakeConn()
        monkeypatch.setattr(
            "app.services.question_service.get_connection", lambda: fake
        )
        total, rows = _db_list_page(
            page=1, page_size=10, knowledge_point_id=None, question_type=None,
            difficulty_min=0.2, difficulty_max=0.8, keyword=None,
        )
        assert total == 7
        assert rows == []
        count_sql, count_params = fake._cursor.executed[0]
        page_sql, page_params = fake._cursor.executed[1]
        assert "q.difficulty >= ?" in count_sql and "q.difficulty <= ?" in count_sql
        assert list(count_params) == [0.2, 0.8]
        # 分页 SQL 中参数追加 OFFSET/FETCH 值
        assert list(page_params) == [0.2, 0.8, 0, 10]

    def test_all_filters_combined(self, monkeypatch):
        """知识点/题型/难度区间/关键词组合筛选全部参数化"""
        fake = self._FakeConn()
        monkeypatch.setattr(
            "app.services.question_service.get_connection", lambda: fake
        )
        _db_list_page(
            page=2, page_size=20, knowledge_point_id="kp_001",
            question_type="single_choice", difficulty_min=0.1, difficulty_max=0.9,
            keyword="方程",
        )
        count_sql, count_params = fake._cursor.executed[0]
        assert "m.knowledge_point_id = ?" in count_sql
        assert "q.type = ?" in count_sql
        assert "q.difficulty >= ?" in count_sql
        assert "q.difficulty <= ?" in count_sql
        assert "q.content LIKE ?" in count_sql
        assert list(count_params) == ["kp_001", "single_choice", 0.1, 0.9, "%方程%"]

    def test_no_difficulty_filter_omits_clauses(self, monkeypatch):
        """不传难度参数时不拼难度条件"""
        fake = self._FakeConn()
        monkeypatch.setattr(
            "app.services.question_service.get_connection", lambda: fake
        )
        _db_list_page(
            page=1, page_size=10, knowledge_point_id=None, question_type=None,
            difficulty_min=None, difficulty_max=None, keyword=None,
        )
        count_sql, _ = fake._cursor.executed[0]
        assert "difficulty" not in count_sql


class TestListDegrade:
    """列表接口降级行为（Neo4j 不可用时名称降级为空，不阻塞列表）"""

    @staticmethod
    def _run(coro):
        return asyncio.run(coro)

    def test_neo4j_down_names_degrade(self, monkeypatch):
        """Neo4j 不可用时 knowledge_point_names 降级为空字符串（与 ID 位置对齐）"""
        monkeypatch.setattr(
            "app.services.question_service._db_list_page",
            lambda *a: (
                1,
                [{
                    "id": "q_001",
                    "content": "题干",
                    "type": "single_choice",
                    "difficulty": 0.3,
                    "created_at": "2026-01-15T10:00:00",
                }],
            ),
        )
        monkeypatch.setattr(
            "app.services.question_service._db_get_question_kp_ids",
            lambda ids: {"q_001": ["kp_001"]},
        )

        def boom(ids):
            raise ServiceUnavailable("Neo4j unavailable (test mock)")

        monkeypatch.setattr("app.services.question_service._db_get_kp_names", boom)

        items, total = self._run(list_questions(page=1, page_size=10))
        assert total == 1
        assert items[0].knowledge_point_ids == ["kp_001"]
        assert items[0].knowledge_point_names == [""]


class TestRoutes:
    """路由注册与统一响应格式（mock 数据库连接，不依赖真实 SQL Server / Neo4j）"""

    @pytest.fixture
    def client(self, monkeypatch):
        """mock get_connection / get_driver：立即抛异常，验证错误处理路径；
        同时以管理员身份覆盖 require_admin 依赖（管理接口已启用鉴权）"""
        import pyodbc

        def boom_conn():
            raise pyodbc.InterfaceError("SQL Server unavailable (test mock)")

        def boom_driver():
            raise ServiceUnavailable("Neo4j unavailable (test mock)")

        fake_admin = UserInfo(
            user_id="adm_001", username="admin_wang", name="王管理", role="admin"
        )
        monkeypatch.setattr("app.services.question_service.get_connection", boom_conn)
        monkeypatch.setattr("app.services.question_service.get_driver", boom_driver)
        app.dependency_overrides[require_admin] = lambda: fake_admin
        yield TestClient(app)
        app.dependency_overrides.clear()

    def test_admin_endpoints_require_auth(self):
        """管理接口已启用鉴权：未携带 Token 返回 401"""
        client = TestClient(app)
        resp = client.get("/api/admin/questions?page=1&page_size=10")
        assert resp.status_code == 401
        assert resp.json()["code"] == 40100

        resp = client.post("/api/admin/questions", json=make_valid_body())
        assert resp.status_code == 401

    def test_admin_endpoints_reject_student_role(self, monkeypatch):
        """学生角色的 Token 访问管理接口返回 403"""
        fake_student = UserInfo(
            user_id="stu_001", username="zhangsan", name="张三", role="student"
        )
        app.dependency_overrides[get_current_user] = lambda: fake_student
        client = TestClient(app)
        try:
            resp = client.get("/api/admin/questions?page=1&page_size=10")
            assert resp.status_code == 403
            assert resp.json()["code"] == 40101
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.parametrize(
        "method, path",
        [
            ("GET", "/api/admin/questions"),
            ("GET", "/api/admin/questions/q_001"),
            ("POST", "/api/admin/questions"),
            ("PUT", "/api/admin/questions/q_001"),
            ("DELETE", "/api/admin/questions/q_001"),
            ("POST", "/api/admin/questions/batch-import"),
        ],
    )
    def test_routes_registered_not_404(self, client, method, path):
        """六个接口均已注册（不返回 404；数据库不可用时返回业务码而非路由不存在）"""
        payload = {}
        if path == "/api/admin/questions/batch-import":
            payload = {"questions": [make_valid_body()]}
        elif method in ("POST", "PUT"):
            payload = make_valid_body()

        resp = client.request(method, path, json=payload)
        assert resp.status_code != 404
        # 统一响应格式：必须含 code/data/message
        body = resp.json()
        assert set(body.keys()) == {"code", "data", "message"}

    def test_list_returns_unified_error_when_sqlserver_down(self, client):
        """SQL Server 不可用时列表接口返回统一错误响应（业务码 50001，不抛裸异常）"""
        resp = client.get("/api/admin/questions?page=1&page_size=10")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 50001
        assert body["data"] is None
        assert body["message"] == "数据库异常，请稍后重试"

    def test_get_detail_returns_unified_error_when_sqlserver_down(self, client):
        """详情接口同样映射数据库异常为 50001"""
        resp = client.get("/api/admin/questions/q_001")
        assert resp.status_code == 200
        assert resp.json()["code"] == 50001

    def test_create_returns_unified_error_when_neo4j_down(self, client):
        """创建前需校验知识点存在性，Neo4j 不可用返回 50002"""
        resp = client.post("/api/admin/questions", json=make_valid_body())
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 50002
        assert body["data"] is None
        assert body["message"] == "图数据库异常，请稍后重试"

    def test_batch_import_returns_unified_error_when_neo4j_down(self, client):
        """批量导入同样先查 Neo4j，不可用返回 50002"""
        resp = client.post(
            "/api/admin/questions/batch-import",
            json={"questions": [make_valid_body()]},
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == 50002

    def test_delete_returns_unified_error_when_sqlserver_down(self, client):
        """删除接口映射数据库异常为 50001"""
        resp = client.delete("/api/admin/questions/q_001")
        assert resp.status_code == 200
        assert resp.json()["code"] == 50001

    def test_invalid_payload_returns_unified_validation_error(self, client):
        """参数校验失败返回统一格式（HTTP 422 + code 40000），而非 Pydantic 默认 detail"""
        resp = client.post(
            "/api/admin/questions",
            json=make_valid_body(difficulty=1.5),  # 超出 0~1
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == 40000
        assert body["data"] is None
        assert "difficulty" in body["message"] or "校验失败" in body["message"]

    def test_invalid_type_query_rejected(self, client):
        """题型筛选值不在枚举内被参数校验拦截"""
        resp = client.get("/api/admin/questions?type=essay")
        assert resp.status_code == 422
        assert resp.json()["code"] == 40000

    def test_difficulty_range_query_valid(self, client):
        """难度区间参数合法时不触发参数校验（数据库不可用返回 50001）"""
        resp = client.get("/api/admin/questions?difficulty_min=0.2&difficulty_max=0.8")
        assert resp.status_code == 200
        assert resp.json()["code"] == 50001

    def test_difficulty_min_greater_than_max_rejected(self, client):
        """难度下限大于上限被参数校验拦截（422 + 40000）"""
        resp = client.get("/api/admin/questions?difficulty_min=0.8&difficulty_max=0.2")
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == 40000
        assert "difficulty_min" in body["message"] or "校验失败" in body["message"]

    def test_difficulty_out_of_range_rejected(self, client):
        """难度区间值超出 0~1 被参数校验拦截"""
        resp = client.get("/api/admin/questions?difficulty_min=1.5")
        assert resp.status_code == 422
        assert resp.json()["code"] == 40000

    def test_page_size_over_max_rejected(self, client):
        """page_size 超过 100 被参数校验拦截"""
        resp = client.get("/api/admin/questions?page=1&page_size=101")
        assert resp.status_code == 422
        assert resp.json()["code"] == 40000

    def test_batch_import_empty_questions_rejected(self, client):
        """批量导入 questions 为空数组被参数校验拦截"""
        resp = client.post(
            "/api/admin/questions/batch-import", json={"questions": []}
        )
        assert resp.status_code == 422
        assert resp.json()["code"] == 40000
