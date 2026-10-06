"""
学员端答题提交接口单元测试

测试覆盖（不依赖真实 SQL Server / JWT 签发，可在任何环境运行）：
- 判题归一化纯函数 judge_answer：单选/多选/判断题各种写法
- 掌握概率贝叶斯更新纯函数 bayesian_mastery_update：上升/下降/边界
- Pydantic 请求模型校验与响应字段契约一致性
- 提交服务逻辑（mock 同步 DB 函数）：单题、批量、题目不存在、
  同知识点批次内链式更新、事务写入参数
- 路由：未认证 401、统一响应格式、题目不存在 40400、数据库异常 50001
"""

import asyncio

import pyodbc
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.answer_submission import (
    AnswerSubmitRequest,
    BatchAnswerResult,
    SubmitAnswerResult,
    SubmitBatchRequest,
)
from app.models.auth import UserInfo
from app.routers.dependencies import require_student
from app.services import answer_submission_service as service
from app.services.answer_submission_service import (
    DEFAULT_MASTERY_PRIOR,
    QuestionNotFoundError,
    bayesian_mastery_update,
    judge_answer,
    _db_apply_submissions,
    submit_answer,
    submit_batch,
)


class TestJudgeAnswer:
    """判题归一化（对照契约：单选字母、多选逗号分隔、判断 true/false）"""

    @pytest.mark.parametrize(
        "correct, student, expected",
        [
            ("B", "B", True),
            ("B", "b", True),        # 大小写不敏感
            ("B", " B ", True),      # 首尾空白
            ("B", "A", False),
            ("A", "B", False),
        ],
    )
    def test_single_choice(self, correct, student, expected):
        assert judge_answer("single_choice", correct, student) is expected

    @pytest.mark.parametrize(
        "correct, student, expected",
        [
            ("A,C", "A,C", True),
            ("A,C", "C,A", True),     # 顺序无关
            ("A,C", "A, C", True),    # 空格容忍
            ("A,C", "a,c", True),     # 大小写不敏感
            ("A,C", "A,A,C", False),  # 重复 label 必须判错，不能静默去重
            ("A,C", "A", False),      # 漏选
            ("A,C", "A,C,D", False),  # 多选
            ("A,C", "", False),       # 空答案
        ],
    )
    def test_multi_choice(self, correct, student, expected):
        assert judge_answer("multi_choice", correct, student) is expected

    @pytest.mark.parametrize(
        "correct, student, expected",
        [
            ("true", "true", True),
            ("true", "TRUE", True),   # 大小写不敏感
            ("false", "false", True),
            ("true", "false", False),
            ("true", "对", True),     # 兼容选项文案「对/错」
            ("false", "错", True),
            ("true", "错", False),
            ("false", "对", False),
        ],
    )
    def test_true_false(self, correct, student, expected):
        assert judge_answer("true_false", correct, student) is expected


class TestBayesianMasteryUpdate:
    """掌握概率贝叶斯后验更新（s=g=0.2 默认，与契约 1.6 配置一致）"""

    def test_correct_increases_from_neutral_prior(self):
        """先验 0.5 答对 → 0.5*0.8/(0.5*0.8+0.5*0.2) = 0.8"""
        assert bayesian_mastery_update(0.5, True) == pytest.approx(0.8)

    def test_wrong_decreases_from_neutral_prior(self):
        """先验 0.5 答错 → 0.5*0.2/(0.5*0.2+0.5*0.8) = 0.2"""
        assert bayesian_mastery_update(0.5, False) == pytest.approx(0.2)

    def test_correct_increases(self):
        after = bayesian_mastery_update(0.88, True)
        assert after > 0.88
        assert after <= 1.0

    def test_wrong_decreases(self):
        after = bayesian_mastery_update(0.88, False)
        assert after < 0.88
        assert after >= 0.0

    def test_full_mastery_stays_full(self):
        """先验 1.0 无论对错都保持 1.0（后验公式性质）"""
        assert bayesian_mastery_update(1.0, True) == pytest.approx(1.0)
        assert bayesian_mastery_update(1.0, False) == pytest.approx(1.0)

    def test_zero_prior_stays_zero_when_wrong(self):
        """先验 0 答错保持 0"""
        assert bayesian_mastery_update(0.0, False) == pytest.approx(0.0)

    def test_prior_clamped_to_unit_interval(self):
        """越界先验钳制到 [0, 1]"""
        assert bayesian_mastery_update(-0.5, True) == pytest.approx(0.0)
        assert bayesian_mastery_update(1.5, False) == pytest.approx(1.0)

    def test_custom_slip_guess(self):
        """自定义参数：s=0.1, g=0.3，先验 0.5 答对 → 0.45/(0.45+0.15)=0.75"""
        assert bayesian_mastery_update(0.5, True, slip=0.1, guess=0.3) == pytest.approx(0.75)

    def test_result_rounded_to_6_decimals(self):
        """结果四舍五入到 6 位小数，接口数值稳定"""
        after = bayesian_mastery_update(0.9, True)
        assert after == pytest.approx(0.972973)


class TestModels:
    """Pydantic 模型（严格对照契约 2.2 请求体）"""

    def test_request_fields_match_contract(self):
        body = AnswerSubmitRequest(
            question_id="q_001", student_answer="B", time_spent=45
        )
        assert set(body.model_dump().keys()) == {
            "question_id",
            "student_answer",
            "time_spent",
        }

    def test_multi_choice_accepts_array_without_collapsing_duplicates(self):
        """多选可用数组提交；重复/非法 label 不能被静默去重。"""
        body = AnswerSubmitRequest(
            question_id="q_002", student_answer=["C", "A"]
        )
        assert body.student_answer == ["C", "A"]
        assert judge_answer("multi_choice", "A,C", body.student_answer) is True
        assert judge_answer("multi_choice", "A,C", ["A", "A", "C"]) is False
        assert judge_answer(
            "multi_choice", "A,C", ["A", "D"], valid_labels=["A", "B", "C"]
        ) is False

    def test_time_spent_optional(self):
        """time_spent 可省略（数据库列允许 NULL）"""
        body = AnswerSubmitRequest(question_id="q_001", student_answer="B")
        assert body.time_spent is None

    @pytest.mark.parametrize(
        "payload",
        [
            {"student_answer": "B", "time_spent": 45},          # 缺 question_id
            {"question_id": "q_001", "time_spent": 45},         # 缺 student_answer
            {"question_id": "", "student_answer": "B"},         # 空题目 ID
            {"question_id": "q_001", "student_answer": ""},     # 空答案
            {"question_id": "q_001", "student_answer": "B", "time_spent": -1},  # 负耗时
        ],
    )
    def test_request_validation_rejects_bad_payload(self, payload):
        with pytest.raises(ValidationError):
            AnswerSubmitRequest.model_validate(payload)

    def test_batch_request_requires_non_empty_answers(self):
        with pytest.raises(ValidationError):
            SubmitBatchRequest(answers=[])

    def test_submit_answer_result_fields_match_contract(self):
        """单题响应字段与契约一致：correct/correct_answer/explanation/mastery_change"""
        result = SubmitAnswerResult(
            correct=True,
            correct_answer="B",
            explanation="解析",
            mastery_change={"kp_001": {"before": 0.88, "after": 0.92}},
        )
        dumped = result.model_dump()
        assert set(dumped.keys()) == {
            "correct",
            "correct_answer",
            "explanation",
            "mastery_change",
        }
        assert dumped["mastery_change"]["kp_001"] == {"before": 0.88, "after": 0.92}

    def test_batch_error_item_defaults(self):
        """判题失败项：correct/correct_answer/explanation 为 None，error 给出原因"""
        item = BatchAnswerResult(question_id="q_999", error="题目不存在")
        assert item.correct is None
        assert item.correct_answer is None
        assert item.explanation is None
        assert item.mastery_change == {}


class TestSubmitService:
    """提交服务逻辑（mock 同步 DB 函数，不连接真实数据库）"""

    QUESTION_Q1 = {
        "type": "single_choice",
        "answer": "B",
        "explanation": "x²-4=0 → x=±2",
        "options": [{"label": "A"}, {"label": "B"}],
    }
    QUESTION_Q2 = {
        "type": "multi_choice",
        "answer": "A,C",
        "explanation": "B 是一元一次",
        "options": [{"label": "A"}, {"label": "B"}, {"label": "C"}],
    }

    @pytest.fixture
    def calls(self):
        """捕获 _db_apply_submissions 调用参数的容器"""
        return []

    def _mock_dbs(
        self,
        monkeypatch,
        calls,
        questions=None,
        kp_map=None,
        mastery_rows=None,
    ):
        monkeypatch.setattr(
            service, "_db_load_questions", lambda ids: questions or {}
        )
        monkeypatch.setattr(
            service, "_db_load_question_kp_ids", lambda ids: kp_map or {}
        )
        monkeypatch.setattr(
            service, "_db_load_mastery_rows", lambda user_id, kp_ids: mastery_rows or {}
        )

        def fake_apply(user_id, records, kp_updates):
            calls.append((user_id, records, kp_updates))

        monkeypatch.setattr(service, "_db_apply_submissions", fake_apply)

    def test_submit_answer_correct(self, monkeypatch, calls):
        """单题判对：返回契约字段，事务写入记录与掌握快照"""
        self._mock_dbs(
            monkeypatch,
            calls,
            questions={"q_001": self.QUESTION_Q1},
            kp_map={"q_001": ["kp_001"]},
        )
        result = asyncio.run(
            submit_answer("stu_001", "q_001", "b", 45)  # 小写答案也应判对
        )
        assert result.correct is True
        assert result.correct_answer == "B"
        assert result.explanation == "x²-4=0 → x=±2"
        assert result.mastery_change["kp_001"].before == pytest.approx(
            DEFAULT_MASTERY_PRIOR
        )
        assert result.mastery_change["kp_001"].after == pytest.approx(0.8)

        # 事务写入参数：1 条记录 + 1 个知识点快照
        user_id, records, kp_updates = calls[0]
        assert user_id == "stu_001"
        assert len(records) == 1
        record = records[0]
        assert record["record_id"].startswith("ar_")
        assert record["question_id"] == "q_001"
        assert record["student_answer"] == "B"
        assert record["is_correct"] is True
        assert record["time_spent"] == 45
        assert kp_updates == {
            "kp_001": {
                "mastery_probability": pytest.approx(0.8),
                "questions_done": 1,
                "correct_count": 1,
            }
        }

    def test_submit_answer_wrong(self, monkeypatch, calls):
        """单题判错：掌握概率下降，correct_count 不变"""
        self._mock_dbs(
            monkeypatch,
            calls,
            questions={"q_001": self.QUESTION_Q1},
            kp_map={"q_001": ["kp_001"]},
        )
        result = asyncio.run(submit_answer("stu_001", "q_001", "A", 30))
        assert result.correct is False
        assert result.mastery_change["kp_001"].before == pytest.approx(0.5)
        assert result.mastery_change["kp_001"].after == pytest.approx(0.2)
        _, _, kp_updates = calls[0]
        assert kp_updates["kp_001"]["questions_done"] == 1
        assert kp_updates["kp_001"]["correct_count"] == 0

    def test_submit_multi_choice_returns_sorted_answer_and_preserves_attempt(self, monkeypatch, calls):
        """多选乱序作答判对，响应按 label 排序，记录保留规范化后的原始顺序。"""
        self._mock_dbs(
            monkeypatch,
            calls,
            questions={"q_002": self.QUESTION_Q2},
            kp_map={"q_002": ["kp_001"]},
        )
        result = asyncio.run(
            submit_answer("stu_001", "q_002", ["C", "A"], 30)
        )
        assert result.correct is True
        assert result.correct_answer == ["A", "C"]
        assert calls[0][1][0]["student_answer"] == "C,A"

    def test_submit_answer_question_not_found(self, monkeypatch, calls):
        """题目不存在（或已下线）抛 QuestionNotFoundError（router 映射 40400）"""
        self._mock_dbs(monkeypatch, calls, questions={})
        with pytest.raises(QuestionNotFoundError):
            asyncio.run(submit_answer("stu_001", "q_999", "B", 10))
        # 题目不存在时不应写入任何数据
        assert calls == []

    def test_submit_answer_existing_mastery_used_as_prior(self, monkeypatch, calls):
        """已有掌握记录时以数据库值为先验，并累计做题数/正确数"""
        self._mock_dbs(
            monkeypatch,
            calls,
            questions={"q_001": self.QUESTION_Q1},
            kp_map={"q_001": ["kp_001"]},
            mastery_rows={
                "kp_001": {
                    "mastery_probability": 0.9,
                    "questions_done": 5,
                    "correct_count": 4,
                }
            },
        )
        result = asyncio.run(submit_answer("stu_001", "q_001", "B", None))
        assert result.mastery_change["kp_001"].before == pytest.approx(0.9)
        assert result.mastery_change["kp_001"].after == pytest.approx(0.972973)

        _, records, kp_updates = calls[0]
        assert records[0]["time_spent"] is None
        assert kp_updates["kp_001"]["questions_done"] == 6
        assert kp_updates["kp_001"]["correct_count"] == 5

    def test_submit_batch_chain_update_same_kp(self, monkeypatch, calls):
        """批次内同一知识点链式更新：后题的 before = 前题更新后的值"""
        self._mock_dbs(
            monkeypatch,
            calls,
            questions={"q_001": self.QUESTION_Q1, "q_002": self.QUESTION_Q2},
            kp_map={"q_001": ["kp_001"], "q_002": ["kp_001"]},
        )
        answers = [
            AnswerSubmitRequest(question_id="q_001", student_answer="B", time_spent=45),
            AnswerSubmitRequest(question_id="q_002", student_answer="A", time_spent=30),
        ]
        result = asyncio.run(submit_batch("stu_001", answers))

        # 第一题答对：0.5 → 0.8；第二题答错（漏选 C）：0.8 → 0.5
        first, second = result.results
        assert first.correct is True
        assert first.mastery_change["kp_001"].before == pytest.approx(0.5)
        assert first.mastery_change["kp_001"].after == pytest.approx(0.8)
        assert second.correct is False
        assert second.mastery_change["kp_001"].before == pytest.approx(0.8)
        assert second.mastery_change["kp_001"].after == pytest.approx(0.5)

        # 最终快照为链式结果：done=2, correct=1
        _, records, kp_updates = calls[0]
        assert len(records) == 2
        assert kp_updates["kp_001"] == {
            "mastery_probability": pytest.approx(0.5),
            "questions_done": 2,
            "correct_count": 1,
        }
        # 汇总统计
        summary = result.summary
        assert summary.total == 2
        assert summary.correct_count == 1
        assert summary.wrong_count == 1
        assert summary.fail_count == 0
        assert summary.correct_rate == pytest.approx(0.5)

    def test_submit_batch_partial_unknown_question(self, monkeypatch, calls):
        """批量中存在不存在题目：该项记 error，不阻塞其他项，不写入其记录"""
        self._mock_dbs(
            monkeypatch,
            calls,
            questions={"q_001": self.QUESTION_Q1},
            kp_map={"q_001": ["kp_001"]},
        )
        answers = [
            AnswerSubmitRequest(question_id="q_001", student_answer="B", time_spent=10),
            AnswerSubmitRequest(question_id="q_999", student_answer="A", time_spent=10),
        ]
        result = asyncio.run(submit_batch("stu_001", answers))

        ok_item, bad_item = result.results
        assert ok_item.error is None
        assert ok_item.correct is True
        assert bad_item.error == "题目不存在"
        assert bad_item.correct is None

        _, records, _ = calls[0]
        assert [r["question_id"] for r in records] == ["q_001"]

        summary = result.summary
        assert summary.total == 2
        assert summary.correct_count == 1
        assert summary.wrong_count == 0
        assert summary.fail_count == 1
        assert summary.correct_rate == pytest.approx(1.0)

    def test_submit_batch_all_unknown_no_write(self, monkeypatch, calls):
        """全部题目不存在：不写库，汇总全部为 fail"""
        self._mock_dbs(monkeypatch, calls, questions={})
        answers = [
            AnswerSubmitRequest(question_id="q_999", student_answer="A"),
            AnswerSubmitRequest(question_id="q_998", student_answer="B"),
        ]
        result = asyncio.run(submit_batch("stu_001", answers))
        assert calls == []
        assert all(item.error == "题目不存在" for item in result.results)
        assert result.summary.fail_count == 2
        assert result.summary.correct_rate == 0.0

    def test_submit_batch_question_without_kp(self, monkeypatch, calls):
        """题目无 Q矩阵关联（脏数据）：正常判题，mastery_change 为空"""
        self._mock_dbs(
            monkeypatch,
            calls,
            questions={"q_001": self.QUESTION_Q1},
            kp_map={},
        )
        answers = [AnswerSubmitRequest(question_id="q_001", student_answer="B")]
        result = asyncio.run(submit_batch("stu_001", answers))
        assert result.results[0].correct is True
        assert result.results[0].mastery_change == {}
        _, records, kp_updates = calls[0]
        assert len(records) == 1
        assert kp_updates == {}

    def test_submit_batch_results_preserve_order(self, monkeypatch, calls):
        """结果顺序与入参一致"""
        self._mock_dbs(
            monkeypatch,
            calls,
            questions={"q_001": self.QUESTION_Q1, "q_002": self.QUESTION_Q2},
            kp_map={"q_001": ["kp_001"], "q_002": ["kp_001"]},
        )
        answers = [
            AnswerSubmitRequest(question_id="q_002", student_answer="A,C"),
            AnswerSubmitRequest(question_id="q_001", student_answer="B"),
        ]
        result = asyncio.run(submit_batch("stu_001", answers))
        assert [item.question_id for item in result.results] == ["q_002", "q_001"]

    def test_database_write_rolls_back_records_and_mastery_together(self, monkeypatch):
        """答题记录或掌握快照任一步失败时必须整体回滚。"""
        class FakeCursor:
            rowcount = 1

            def __init__(self):
                self.insert_count = 0

            def execute(self, sql, params=()):
                if sql.startswith("INSERT INTO answer_records"):
                    self.insert_count += 1
                    if self.insert_count == 2:
                        raise pyodbc.Error("forced rollback")
                return self

            def fetchone(self):
                return (1,)

        class FakeConnection:
            def __init__(self):
                self.cursor_instance = FakeCursor()
                self.committed = False
                self.rolled_back = False
                self.closed = False

            def cursor(self):
                return self.cursor_instance

            def commit(self):
                self.committed = True

            def rollback(self):
                self.rolled_back = True

            def close(self):
                self.closed = True

        connection = FakeConnection()
        monkeypatch.setattr(service, "get_connection", lambda: connection)
        with pytest.raises(pyodbc.Error):
            _db_apply_submissions(
                "stu_001",
                [
                    {"record_id": "ar_1", "question_id": "q_1", "student_answer": "A", "is_correct": True, "time_spent": 1},
                    {"record_id": "ar_2", "question_id": "q_2", "student_answer": "B", "is_correct": False, "time_spent": 2},
                ],
                {},
            )
        assert connection.rolled_back is True
        assert connection.committed is False
        assert connection.closed is True


class _MockDbError(pyodbc.Error):
    """模拟 pyodbc 数据库异常（仅测试用，保证能被 except pyodbc.Error 捕获）"""


class TestRoutes:
    """路由注册、认证要求与统一响应格式（mock 数据库层）"""

    @pytest.fixture
    def auth_client(self, monkeypatch):
        """覆盖 require_student 依赖，模拟已登录学生"""
        fake_user = UserInfo(
            user_id="stu_001", username="zhangsan", name="张三", role="student"
        )
        app.dependency_overrides[require_student] = lambda: fake_user
        yield TestClient(app)
        app.dependency_overrides.clear()

    def _mock_ok_db(self, monkeypatch):
        monkeypatch.setattr(
            service,
            "_db_load_questions",
            lambda ids: {
                "q_001": {
                    "type": "single_choice",
                    "answer": "B",
                    "explanation": "x=±2，选项中 B 正确",
                }
            },
        )
        monkeypatch.setattr(
            service, "_db_load_question_kp_ids", lambda ids: {"q_001": ["kp_001"]}
        )
        monkeypatch.setattr(
            service,
            "_db_load_mastery_rows",
            lambda user_id, kp_ids: {"kp_001": {"mastery_probability": 0.88, "questions_done": 8, "correct_count": 6}},
        )
        monkeypatch.setattr(service, "_db_apply_submissions", lambda *args: None)

    def test_submit_answer_requires_auth(self, monkeypatch):
        """未携带 Token 返回 401"""
        resp = TestClient(app).post(
            "/api/student/submit-answer",
            json={"question_id": "q_001", "student_answer": "B", "time_spent": 45},
        )
        assert resp.status_code == 401

    def test_submit_batch_requires_auth(self, monkeypatch):
        """批量接口同样要求登录"""
        resp = TestClient(app).post(
            "/api/student/submit-batch",
            json={"answers": [{"question_id": "q_001", "student_answer": "B"}]},
        )
        assert resp.status_code == 401

    def test_submit_answer_success_response(self, monkeypatch, auth_client):
        """单题提交成功：统一响应格式 + 契约字段"""
        self._mock_ok_db(monkeypatch)
        resp = auth_client.post(
            "/api/student/submit-answer",
            json={"question_id": "q_001", "student_answer": "B", "time_spent": 45},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"code", "data", "message"}
        assert body["code"] == 0
        data = body["data"]
        assert data["correct"] is True
        assert data["correct_answer"] == "B"
        assert data["explanation"] == "x=±2，选项中 B 正确"
        assert data["mastery_change"]["kp_001"]["before"] == 0.88
        assert data["mastery_change"]["kp_001"]["after"] > 0.88

    def test_submit_answer_question_not_found(self, monkeypatch, auth_client):
        """题目不存在返回 40400 统一错误"""
        monkeypatch.setattr(service, "_db_load_questions", lambda ids: {})
        resp = auth_client.post(
            "/api/student/submit-answer",
            json={"question_id": "q_999", "student_answer": "B"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 40400
        assert body["data"] is None
        assert body["message"] == "题目不存在"

    def test_submit_batch_response(self, monkeypatch, auth_client):
        """批量提交：results（每题结果汇总）+ summary 统计"""
        monkeypatch.setattr(
            service,
            "_db_load_questions",
            lambda ids: {
                "q_001": {"type": "single_choice", "answer": "B", "explanation": ""},
                "q_002": {"type": "single_choice", "answer": "A", "explanation": ""},
            },
        )
        monkeypatch.setattr(
            service,
            "_db_load_question_kp_ids",
            lambda ids: {"q_001": ["kp_001"], "q_002": ["kp_002"]},
        )
        monkeypatch.setattr(
            service, "_db_load_mastery_rows", lambda user_id, kp_ids: {}
        )
        monkeypatch.setattr(service, "_db_apply_submissions", lambda *args: None)

        resp = auth_client.post(
            "/api/student/submit-batch",
            json={
                "answers": [
                    {"question_id": "q_001", "student_answer": "B", "time_spent": 45},
                    {"question_id": "q_002", "student_answer": "B", "time_spent": 30},
                ]
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        assert [item["question_id"] for item in data["results"]] == ["q_001", "q_002"]
        assert data["results"][0]["correct"] is True
        assert data["results"][1]["correct"] is False
        assert data["summary"] == {
            "total": 2,
            "correct_count": 1,
            "wrong_count": 1,
            "fail_count": 0,
            "correct_rate": 0.5,
        }

    def test_submit_batch_unknown_item_in_result(self, monkeypatch, auth_client):
        """批量中不存在的题目记入该项 error，不阻塞其他题"""
        monkeypatch.setattr(
            service,
            "_db_load_questions",
            lambda ids: {
                "q_001": {"type": "single_choice", "answer": "B", "explanation": ""}
            },
        )
        monkeypatch.setattr(
            service, "_db_load_question_kp_ids", lambda ids: {"q_001": ["kp_001"]}
        )
        monkeypatch.setattr(
            service, "_db_load_mastery_rows", lambda user_id, kp_ids: {}
        )
        monkeypatch.setattr(service, "_db_apply_submissions", lambda *args: None)

        resp = auth_client.post(
            "/api/student/submit-batch",
            json={
                "answers": [
                    {"question_id": "q_001", "student_answer": "B"},
                    {"question_id": "q_999", "student_answer": "A"},
                ]
            },
        )
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["results"][0]["error"] is None
        assert data["results"][1]["error"] == "题目不存在"
        assert data["summary"]["fail_count"] == 1
        assert data["summary"]["correct_rate"] == 1.0

    def test_db_error_maps_to_50001(self, monkeypatch, auth_client):
        """数据库异常返回 50001 统一错误，不暴露堆栈"""

        def boom(ids):
            raise _MockDbError("sql down (test mock)")

        monkeypatch.setattr(service, "_db_load_questions", boom)
        resp = auth_client.post(
            "/api/student/submit-answer",
            json={"question_id": "q_001", "student_answer": "B"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 50001
        assert body["message"] == "数据库异常，请稍后重试"
