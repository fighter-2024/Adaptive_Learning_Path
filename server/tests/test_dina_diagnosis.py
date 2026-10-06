"""
DINA 认知诊断模块单元测试

测试覆盖（不依赖真实 SQL Server / JWT 签发，可在任何环境运行）：
- QMatrix：构建去重、行列索引、位掩码、活跃属性、空矩阵校验
- EM 题目参数估计（de la Torre 2009）：
    * 精确全枚举 EM 在合成数据上恢复真实 s/g
    * 置信传播（BP）兜底路径：树结构因子图上与精确 EM 一致、
      大活跃集自动降级
    * 收敛阈值 / 迭代上限语义
    * 无人作答的题目保持初始参数
    * s/g 初始值钳制 [0.1, 0.3]（总则第七条）
- 贝叶斯后验推断 α：
    * 单知识点解析解（与答题模块 bayesian_mastery_update 交叉验证）
    * 多知识点题目、未作答知识点保持先验
    * 置信传播降级路径
- 诊断服务 diagnose_student（mock 同步 DB 函数）：
    * 完整流程与写库参数、答题记录不足 / Q 矩阵为空异常
- 路由：未认证 401、统一响应格式、40002 / 50001 错误映射
"""

import asyncio
import json
import random
import re
from datetime import datetime

import pyodbc
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.auth import UserInfo
from app.models.diagnosis import DiagnosisResult, DiagnosisTrace
from app.routers.dependencies import require_student
from app.routers.student import diagnosis as diagnosis_router_module
from app.services import diagnosis_service as service
from app.services.answer_submission_service import bayesian_mastery_update
from app.services.dina import (
    QMatrix,
    QMatrixError,
    estimate_item_parameters,
    infer_mastery_posterior,
)
from app.services.dina.em import clamp_initial_parameters
from app.services.diagnosis_service import (
    InsufficientAnswerError,
    aggregate_latest_attempts,
    diagnose_student,
)

# 合成数据真实参数（DINA：失误率 s = 猜测率 g = 0.2）
TRUE_S = 0.2
TRUE_G = 0.2


def _make_synthetic(n_students: int = 400, seed: int = 42):
    """生成 K=2、J=3 的合成作答数据

    Q 矩阵：q0=[kp0]，q1=[kp1]，q2=[kp0,kp1]；
    掌握模式分布 P(00,10,01,11) = (0.1, 0.4, 0.1, 0.4)；
    作答按 s=g=0.2 采样（η=1 答对概率 0.8，η=0 猜对概率 0.2）。

    Returns:
        (qmatrix, responses, true_marginals)
    """
    rng = random.Random(seed)
    qmatrix = QMatrix(
        [
            ("q_001", "kp_001"),
            ("q_002", "kp_002"),
            ("q_003", "kp_001"),
            ("q_003", "kp_002"),
        ]
    )
    patterns = ["00", "10", "01", "11"]
    weights = [0.1, 0.4, 0.1, 0.4]
    responses = []
    for _ in range(n_students):
        pattern = rng.choices(patterns, weights=weights)[0]
        a0, a1 = int(pattern[0]), int(pattern[1])
        responses.append(
            {
                0: 1 if rng.random() < (0.8 if a0 else 0.2) else 0,
                1: 1 if rng.random() < (0.8 if a1 else 0.2) else 0,
                2: 1 if rng.random() < (0.8 if (a0 and a1) else 0.2) else 0,
            }
        )
    return qmatrix, responses, [0.8, 0.5]


# ==================== QMatrix ====================


class TestQMatrix:
    """Q 矩阵数据结构（对应 q_matrix 表加载结果）"""

    def test_build_and_indices(self):
        qm = QMatrix([("q_001", "kp_001"), ("q_002", "kp_002")])
        assert qm.J == 2
        assert qm.K == 2
        assert qm.question_ids == ["q_001", "q_002"]
        assert qm.attribute_ids == ["kp_001", "kp_002"]
        assert qm.question_index("q_001") == 0
        assert qm.attribute_index("kp_002") == 1
        assert qm.has_question("q_001") is True
        assert qm.has_question("q_999") is False

    def test_duplicate_rows_deduplicated(self):
        qm = QMatrix(
            [("q_001", "kp_001"), ("q_001", "kp_001"), ("q_001", "kp_002")]
        )
        assert qm.J == 1
        assert qm.K == 2

    def test_q_vector_and_mask(self):
        qm = QMatrix(
            [("q_001", "kp_001"), ("q_001", "kp_002"), ("q_002", "kp_001")]
        )
        assert qm.q_vector("q_001") == [1, 1]
        assert qm.q_vector("q_002") == [1, 0]
        assert qm.question_mask("q_001") == 0b11
        assert qm.attribute_ids_of("q_001") == ["kp_001", "kp_002"]

    def test_active_attribute_indices(self):
        qm = QMatrix(
            [
                ("q_001", "kp_001"),
                ("q_002", "kp_002"),
                ("q_003", "kp_001"),
                ("q_003", "kp_002"),
            ]
        )
        assert qm.active_attribute_indices(["q_001"]) == [0]
        assert qm.active_attribute_indices(["q_003"]) == [0, 1]
        assert qm.active_attribute_indices(["q_001", "q_002"]) == [0, 1]

    def test_empty_rows_raise(self):
        with pytest.raises(QMatrixError):
            QMatrix([])

    def test_validate_ok(self):
        # 每个题目至少一个知识点（总则第七条），合法矩阵校验通过
        QMatrix([("q_001", "kp_001")]).validate()

    def test_question_index_missing_raises(self):
        qm = QMatrix([("q_001", "kp_001")])
        with pytest.raises(KeyError):
            qm.question_index("q_999")


# ==================== EM 题目参数估计 ====================


class TestEmExact:
    """全枚举精确 EM（de la Torre 2009）在合成数据上恢复真实参数"""

    def test_recovers_slip_and_guess(self):
        qmatrix, responses, marginals = _make_synthetic()
        result = estimate_item_parameters(
            responses, qmatrix, marginals,
            s_init=0.2, g_init=0.2,
        )
        assert result.converged is True
        assert 1 <= result.iterations < 500
        for j in range(qmatrix.J):
            assert result.slip[j] == pytest.approx(TRUE_S, abs=0.1)
            assert result.guess[j] == pytest.approx(TRUE_G, abs=0.1)

    def test_loglikelihood_increases_overall(self):
        qmatrix, responses, marginals = _make_synthetic()
        result = estimate_item_parameters(responses, qmatrix, marginals)
        history = result.loglikelihood_history
        assert len(history) >= 2
        assert history[-1] > history[0]

    def test_iteration_cap_respected(self):
        qmatrix, responses, marginals = _make_synthetic()
        result = estimate_item_parameters(
            responses, qmatrix, marginals,
            max_iterations=2, convergence_threshold=0.0,  # 阈值 0 保证不可能收敛
        )
        assert result.iterations == 2
        assert result.converged is False

    def test_unobserved_question_keeps_initial_params(self):
        """无人作答的题目数据不足，保持初始参数（分母保护）"""
        qmatrix, responses, marginals = _make_synthetic()
        for resp in responses:
            resp.pop(2)  # q2 无人作答
        result = estimate_item_parameters(responses, qmatrix, marginals)
        assert result.slip[2] == pytest.approx(0.2)
        assert result.guess[2] == pytest.approx(0.2)
        # 有作答的题目正常更新
        assert result.slip[0] != pytest.approx(0.2, abs=1e-9)

    def test_no_data_returns_initial_params(self):
        qmatrix, _, marginals = _make_synthetic()
        result = estimate_item_parameters([], qmatrix, marginals)
        assert result.iterations == 0
        assert result.converged is True
        assert result.slip == [0.2] * qmatrix.J
        assert result.guess == [0.2] * qmatrix.J

    def test_initial_parameters_clamped_to_range(self):
        """总则第七条：s/g 初始值钳制到 [0.1, 0.3]"""
        assert clamp_initial_parameters(0.05, 0.9) == (0.1, 0.3)
        assert clamp_initial_parameters(0.15, 0.25) == (0.15, 0.25)


class TestEmFallbackBP:
    """置信传播兜底路径：每学生活跃知识点 2^m 超上限时自动降级"""

    def test_bp_matches_exact_on_tree_case(self):
        """K=2 因子图为树（q0-a0-q2-a1-q1），BP 收敛于精确后验"""
        qmatrix, responses, marginals = _make_synthetic()
        exact = estimate_item_parameters(responses, qmatrix, marginals)
        approx = estimate_item_parameters(
            responses, qmatrix, marginals, max_classes=1  # 强制走 BP
        )
        for j in range(qmatrix.J):
            assert approx.slip[j] == pytest.approx(exact.slip[j], abs=0.05)
            assert approx.guess[j] == pytest.approx(exact.guess[j], abs=0.05)
        assert approx.slip[0] == pytest.approx(TRUE_S, abs=0.05)

    def test_large_attribute_space_falls_back(self):
        """K=12 树结构：每学生活跃集 2^12=4096 > 1024 自动走 BP，仍恢复参数"""
        rng = random.Random(7)
        rows = []
        # 6 道题，每道覆盖两个知识点：{i, i+6}（森林结构，BP 精确）
        for i in range(6):
            rows.append((f"q_{i}", f"kp_{i}"))
            rows.append((f"q_{i}", f"kp_{i + 6}"))
        qmatrix = QMatrix(rows)
        responses = []
        for _ in range(300):
            resp = {}
            for i in range(6):
                mastered_all = rng.random() < 0.5 and rng.random() < 0.5
                resp[i] = 1 if rng.random() < (0.8 if mastered_all else 0.2) else 0
            responses.append(resp)
        result = estimate_item_parameters(
            responses, qmatrix, [0.5] * 12,
        )
        assert result.iterations >= 1
        assert result.converged is True
        assert result.loglikelihood_history == []  # BP 不产出精确似然轨迹
        for j in range(qmatrix.J):
            assert result.slip[j] == pytest.approx(TRUE_S, abs=0.1)
            assert result.guess[j] == pytest.approx(TRUE_G, abs=0.1)


# ==================== 贝叶斯后验推断 α ====================


class TestPosteriorInference:
    """贝叶斯后验推断（先验 = 上一轮 α）"""

    def test_single_attribute_matches_bayesian_update(self):
        """单知识点解析解与答题模块的贝叶斯更新公式交叉验证"""
        qm = QMatrix([("q_001", "kp_001")])
        slip = [0.2]
        guess = [0.2]
        prior = [0.5]
        p_correct = infer_mastery_posterior({0: 1}, qm, slip, guess, prior)
        p_wrong = infer_mastery_posterior({0: 0}, qm, slip, guess, prior)
        assert p_correct[0] == pytest.approx(bayesian_mastery_update(0.5, True))
        assert p_wrong[0] == pytest.approx(bayesian_mastery_update(0.5, False))
        assert p_correct[0] == pytest.approx(0.8)
        assert p_wrong[0] == pytest.approx(0.2)

    def test_two_attribute_question_analytical_value(self):
        """题目考察 {kp0,kp1}、答对、先验 0.5：P(α_k=1) = 0.25/0.35 ≈ 0.7143"""
        qm = QMatrix([("q_001", "kp_001"), ("q_001", "kp_002")])
        result = infer_mastery_posterior(
            {0: 1}, qm, [0.2], [0.2], [0.5, 0.5]
        )
        assert result[0] == pytest.approx(0.25 / 0.35)
        assert result[1] == pytest.approx(0.25 / 0.35)

    def test_unattempted_attribute_keeps_prior(self):
        """未在作答题目中出现过的知识点：后验 = 先验（无证据）"""
        qm = QMatrix(
            [("q_001", "kp_001"), ("q_002", "kp_002")]
        )
        result = infer_mastery_posterior(
            {0: 1}, qm, [0.2, 0.2], [0.2, 0.2], [0.3, 0.7]
        )
        assert result[0] == pytest.approx(0.3 * 0.8 / (0.3 * 0.8 + 0.7 * 0.2))
        assert result[1] == pytest.approx(0.7)

    def test_empty_responses_return_prior(self):
        qm = QMatrix([("q_001", "kp_001"), ("q_002", "kp_002")])
        result = infer_mastery_posterior({}, qm, [0.2, 0.2], [0.2, 0.2], [0.4, 0.6])
        assert result == pytest.approx([0.4, 0.6])

    def test_bp_fallback_large_active_set(self):
        """作答涉及 15 个知识点（2^15 超上限）时降级置信传播，结果合法"""
        rows = []
        for i in range(15):
            rows.append((f"q_{i}", f"kp_{i}"))
            rows.append((f"q_{i}", f"kp_{(i + 1) % 15}"))
        qm = QMatrix(rows)
        slip = [0.2] * 15
        guess = [0.2] * 15
        prior = [0.5] * 15
        responses = {i: 1 for i in range(15)}
        result = infer_mastery_posterior(
            responses, qm, slip, guess, prior, max_classes=1024
        )
        assert len(result) == 15
        assert all(0.0 <= p <= 1.0 for p in result)
        # 全部答对且 s=g=0.2，后验应显著高于先验
        assert all(p > 0.6 for p in result)

    def test_multi_question_evidence_accumulates(self):
        """多题证据叠加：先答错再答对，后验介于两者之间且高于单题答对"""
        qm = QMatrix([("q_001", "kp_001")])
        single = infer_mastery_posterior({0: 1}, qm, [0.2], [0.2], [0.5])
        both = infer_mastery_posterior({0: 1}, qm, [0.2], [0.2], [0.5])
        # 同题重复提交视为多次独立证据：需要两道不同题目
        qm2 = QMatrix([("q_001", "kp_001"), ("q_002", "kp_001")])
        two_correct = infer_mastery_posterior(
            {0: 1, 1: 1}, qm2, [0.2, 0.2], [0.2, 0.2], [0.5]
        )
        mixed = infer_mastery_posterior(
            {0: 1, 1: 0}, qm2, [0.2, 0.2], [0.2, 0.2], [0.5]
        )
        assert two_correct[0] > single[0]
        assert mixed[0] == pytest.approx(0.5)  # 一正一负证据抵消


# ==================== 诊断服务 ====================


class TestDiagnosisService:
    """diagnose_student 完整流程（mock 同步 DB 函数）"""

    QMATRIX_ROWS = [("q_001", "kp_001"), ("q_001", "kp_002"), ("q_002", "kp_001")]

    def _mock_dbs(self, monkeypatch, calls, qmatrix_rows=None, records=None,
                  mastery_rows=None, stats=None):
        monkeypatch.setattr(
            service, "_db_load_qmatrix_rows",
            lambda: list(qmatrix_rows if qmatrix_rows is not None else self.QMATRIX_ROWS),
        )
        monkeypatch.setattr(
            service, "_db_load_all_answer_records",
            lambda: list(records if records is not None else []),
        )
        monkeypatch.setattr(
            service, "_db_load_mastery_rows",
            lambda: list(mastery_rows if mastery_rows is not None else []),
        )
        monkeypatch.setattr(
            service, "_db_load_kp_statistics",
            lambda user_id, kp_ids: dict(stats or {}),
        )

        def fake_save(session_id, user_id, alpha_json, question_count,
                      diagnosed_at, kp_updates):
            calls.append(
                (session_id, user_id, alpha_json, question_count,
                 diagnosed_at, kp_updates)
            )

        monkeypatch.setattr(service, "_db_save_diagnosis", fake_save)

    def test_happy_path_writes_session_and_mastery(self, monkeypatch):
        calls = []
        self._mock_dbs(
            monkeypatch,
            calls,
            records=[
                ("stu_001", "q_001", True),
                ("stu_001", "q_002", False),
                ("stu_002", "q_001", True),
            ],
            mastery_rows=[
                ("stu_001", "kp_001", 0.8),
                ("stu_001", "kp_002", 0.6),
                ("stu_002", "kp_001", 0.5),
            ],
            stats={
                "kp_001": {"questions_done": 2, "correct_count": 1},
                "kp_002": {"questions_done": 1, "correct_count": 1},
            },
        )
        result = asyncio.run(diagnose_student("stu_001"))

        # 响应结构：alpha_vector 维度 = Q 矩阵知识点总数
        assert set(result.alpha_vector.keys()) == {"kp_001", "kp_002"}
        assert all(0.0 <= p <= 1.0 for p in result.alpha_vector.values())
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", result.diagnosed_at)

        # 写库参数
        assert len(calls) == 1
        session_id, user_id, alpha_json, question_count, _, kp_updates = calls[0]
        assert session_id.startswith("diag_")
        assert user_id == "stu_001"
        assert question_count == 2  # 该生 2 条有效答题记录
        stored_alpha = json.loads(alpha_json)
        assert stored_alpha == pytest.approx(result.alpha_vector)
        # 仅更新有作答证据的知识点（两题覆盖 kp_001、kp_002）
        assert set(kp_updates.keys()) == {"kp_001", "kp_002"}
        assert kp_updates["kp_001"]["questions_done"] == 2
        assert kp_updates["kp_001"]["correct_count"] == 1
        assert kp_updates["kp_002"]["mastery_probability"] == pytest.approx(
            result.alpha_vector["kp_002"]
        )

    def test_no_records_raises(self, monkeypatch):
        calls = []
        self._mock_dbs(monkeypatch, calls, records=[])
        with pytest.raises(InsufficientAnswerError):
            asyncio.run(diagnose_student("stu_001"))
        assert calls == []

    def test_records_without_qmatrix_raises(self, monkeypatch):
        """答题记录的题目无 Q 矩阵关联：视为无有效记录"""
        calls = []
        self._mock_dbs(
            monkeypatch,
            calls,
            records=[("stu_001", "q_999", True)],
        )
        with pytest.raises(InsufficientAnswerError):
            asyncio.run(diagnose_student("stu_001"))
        assert calls == []

    def test_empty_qmatrix_raises(self, monkeypatch):
        calls = []
        self._mock_dbs(
            monkeypatch,
            calls,
            qmatrix_rows=[],
            records=[("stu_001", "q_001", True)],
        )
        with pytest.raises(InsufficientAnswerError):
            asyncio.run(diagnose_student("stu_001"))
        assert calls == []

    def test_other_students_records_not_enough(self, monkeypatch):
        """仅其他学生有记录、本人无记录：仍属答题记录不足"""
        calls = []
        self._mock_dbs(
            monkeypatch,
            calls,
            records=[("stu_002", "q_001", True)],
        )
        with pytest.raises(InsufficientAnswerError):
            asyncio.run(diagnose_student("stu_001"))
        assert calls == []

    def test_prior_used_for_unattempted_attribute(self, monkeypatch):
        """作答未涉及的知识点在 α 向量中保持上一轮先验值"""
        calls = []
        self._mock_dbs(
            monkeypatch,
            calls,
            records=[("stu_001", "q_002", True)],  # 仅覆盖 kp_001
            mastery_rows=[
                ("stu_001", "kp_001", 0.8),
                ("stu_001", "kp_002", 0.6),
            ],
        )
        result = asyncio.run(diagnose_student("stu_001"))
        assert "kp_002" in result.alpha_vector  # 维度仍 = 知识点总数
        assert result.alpha_vector["kp_002"] == pytest.approx(0.6)  # 无证据保持先验
        # user_kp_mastery 只更新有证据的 kp_001
        assert set(calls[0][5].keys()) == {"kp_001"}

    def test_repeat_attempts_use_latest_attempt_and_keep_trace_count(self, monkeypatch):
        """同题重做不被偶然覆盖：按时间取最近一次，trace 记录聚合数。"""
        calls = []
        self._mock_dbs(
            monkeypatch,
            calls,
            records=[
                ("stu_001", "q_001", True, datetime(2026, 10, 1, 10, 0)),
                ("stu_001", "q_001", False, datetime(2026, 10, 1, 11, 0)),
                ("stu_001", "q_002", True, datetime(2026, 10, 1, 12, 0)),
                # 其他学生即使出现在旧适配器返回值中也不能进入本次诊断。
                ("stu_002", "q_001", True, datetime(2026, 10, 1, 13, 0)),
            ],
            stats={
                "kp_001": {"questions_done": 3, "correct_count": 1},
                "kp_002": {"questions_done": 1, "correct_count": 1},
            },
        )

        result = asyncio.run(diagnose_student("stu_001"))

        assert result.trace is not None
        assert result.trace.repeat_strategy == "latest_attempt"
        assert result.trace.answer_count == 2
        assert result.trace.answer_time_from == "2026-10-01T11:00:00"
        assert result.trace.answer_time_to == "2026-10-01T12:00:00"
        assert calls[0][3] == 2


class _LatestDiagnosisCursor:
    def __init__(self, row, visible_user=None):
        self.row = row
        self.visible_user = visible_user
        self.query = None
        self.params = None

    def execute(self, query, params):
        self.query = query
        self.params = params

    def fetchone(self):
        if self.visible_user is not None and self.params != (self.visible_user,):
            return None
        return self.row


class _LatestDiagnosisConnection:
    def __init__(self, row, visible_user=None):
        self.cursor_obj = _LatestDiagnosisCursor(row, visible_user)
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


def test_latest_diagnosis_restores_new_trace_and_scopes_user(monkeypatch):
    """0002 新会话 GET 恢复完整 trace，SQL 参数仍限定当前学生。"""
    conn = _LatestDiagnosisConnection(
        (
            '{"kp_001": 0.91}',
            3,
            datetime(2026, 10, 6, 12, 0),
            "dina-v1",
            "default-v1",
            datetime(2026, 10, 1, 10, 0),
            datetime(2026, 10, 5, 18, 30),
            "latest_attempt",
            1,
            4,
        )
    )
    monkeypatch.setattr(service, "get_connection", lambda: conn)

    result = service._db_load_latest_diagnosis("stu_001")

    assert result is not None
    assert result.trace == DiagnosisTrace(
        algorithm_version="dina-v1",
        parameter_version="default-v1",
        answer_count=3,
        answer_time_from="2026-10-01T10:00:00",
        answer_time_to="2026-10-05T18:30:00",
        repeat_strategy="latest_attempt",
        converged=True,
        iterations=4,
    )
    assert conn.cursor_obj.params == ("stu_001",)
    assert "algorithm_version" in conn.cursor_obj.query
    assert conn.closed is True


def test_latest_diagnosis_old_migrated_row_has_no_trace(monkeypatch):
    """0002 迁移前历史行虽有默认字段，但无答题时间时保持 trace 为空。"""
    conn = _LatestDiagnosisConnection(
        (
            '{"kp_001": 0.72}',
            20,
            datetime(2026, 7, 1, 10, 0),
            "dina-v1",
            "default-v1",
            None,
            None,
            "latest_attempt",
            0,
            0,
        )
    )
    monkeypatch.setattr(service, "get_connection", lambda: conn)

    result = service._db_load_latest_diagnosis("stu_001")

    assert result is not None
    assert result.alpha_vector == {"kp_001": 0.72}
    assert result.diagnosed_at == "2026-07-01T10:00:00"
    assert result.trace is None


def test_latest_diagnosis_does_not_return_another_student(monkeypatch):
    """最近诊断查询必须按当前 user_id 隔离，不能读到其他学生的会话。"""
    conn = _LatestDiagnosisConnection(
        ('{"kp_002": 0.8}', 2, datetime(2026, 10, 2, 9, 0), "dina-v1", "default-v1",
         datetime(2026, 10, 1, 9, 0), datetime(2026, 10, 2, 9, 0),
         "latest_attempt", 1, 2),
        visible_user="stu_002",
    )
    monkeypatch.setattr(service, "get_connection", lambda: conn)

    result = service._db_load_latest_diagnosis("stu_001")

    assert result is None
    assert conn.cursor_obj.params == ("stu_001",)


def test_latest_diagnosis_legacy_two_column_adapter_has_no_trace(monkeypatch):
    """尚未返回 0002 列的旧适配器仍可恢复 alpha/time。"""
    conn = _LatestDiagnosisConnection(
        ('{"kp_001": 0.6}', datetime(2026, 6, 1, 9, 0))
    )
    monkeypatch.setattr(service, "get_connection", lambda: conn)

    result = service._db_load_latest_diagnosis("stu_001")

    assert result is not None
    assert result.diagnosed_at == "2026-06-01T09:00:00"
    assert result.trace is None


def test_aggregate_latest_attempts_tie_breaks_by_record_order():
    """created_at 相同时，后到的稳定 record_order 作为最新记录。"""
    records = [
        ("stu_001", "q_001", True, datetime(2026, 10, 1, 10, 0)),
        ("stu_001", "q_001", False, datetime(2026, 10, 1, 10, 0)),
    ]
    result = aggregate_latest_attempts(records, "stu_001")
    assert len(result) == 1
    assert result[0].is_correct is False


def test_dina_handles_all_correct_and_all_wrong_single_attempt():
    """极端但合法的单条全对/全错数据不应抛异常或越界。"""
    qmatrix = QMatrix([("q_001", "kp_001")])
    for answer in (1, 0):
        result = estimate_item_parameters(
            [{0: answer}], qmatrix, [0.5], max_iterations=3
        )
        assert 0.0 <= result.slip[0] <= 1.0
        assert 0.0 <= result.guess[0] <= 1.0


# ==================== 路由 ====================


class _MockDbError(pyodbc.Error):
    """模拟 pyodbc 数据库异常（仅测试用，保证能被 except pyodbc.Error 捕获）"""


class TestRoutes:
    """路由注册、认证要求与统一响应格式"""

    @pytest.fixture
    def auth_client(self, monkeypatch):
        """覆盖 require_student 依赖，模拟已登录学生"""
        fake_user = UserInfo(
            user_id="stu_001", username="zhangsan", name="张三", role="student"
        )
        app.dependency_overrides[require_student] = lambda: fake_user
        yield TestClient(app)
        app.dependency_overrides.clear()

    def test_diagnosis_requires_auth(self, monkeypatch):
        """未携带 Token 返回 401"""
        resp = TestClient(app).post("/api/student/diagnosis")
        assert resp.status_code == 401

    def test_diagnosis_success_response(self, monkeypatch, auth_client):
        """诊断成功：统一响应格式 + 契约字段（alpha_vector / diagnosed_at）"""
        async def fake_diagnose(user_id):
            return DiagnosisResult(
                alpha_vector={"kp_001": 0.92, "kp_002": 0.78},
                diagnosed_at="2026-03-20T18:30:00",
            )

        monkeypatch.setattr(diagnosis_router_module, "diagnose_student", fake_diagnose)
        resp = auth_client.post("/api/student/diagnosis")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"code", "data", "message"}
        assert body["code"] == 0
        assert body["data"] == {
            "alpha_vector": {"kp_001": 0.92, "kp_002": 0.78},
            "diagnosed_at": "2026-03-20T18:30:00",
        }

    def test_diagnosis_insufficient_data(self, monkeypatch, auth_client):
        """答题记录不足返回 40002 统一错误"""

        async def fake_diagnose(user_id):
            raise InsufficientAnswerError("学生 stu_001 无有效答题记录")

        monkeypatch.setattr(diagnosis_router_module, "diagnose_student", fake_diagnose)
        resp = auth_client.post("/api/student/diagnosis")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 40002
        assert body["data"] is None
        assert body["message"] == "答题记录不足，无法进行认知诊断"

    def test_db_error_maps_to_50001(self, monkeypatch, auth_client):
        """数据库异常返回 50001 统一错误，不暴露堆栈"""

        async def fake_diagnose(user_id):
            raise _MockDbError("sql down (test mock)")

        monkeypatch.setattr(diagnosis_router_module, "diagnose_student", fake_diagnose)
        resp = auth_client.post("/api/student/diagnosis")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 50001
        assert body["message"] == "数据库异常，请稍后重试"

    def test_latest_diagnosis_success_response(self, monkeypatch, auth_client):
        """诊断页可恢复最近一次 α 向量和 trace。"""
        async def fake_latest(user_id):
            return DiagnosisResult(
                alpha_vector={"kp_001": 0.9},
                diagnosed_at="2026-10-05T10:00:00",
                trace=DiagnosisTrace(
                    algorithm_version="dina-v1",
                    parameter_version="default-v1",
                    answer_count=2,
                    answer_time_from="2026-10-01T10:00:00",
                    answer_time_to="2026-10-05T09:00:00",
                    repeat_strategy="latest_attempt",
                    converged=True,
                    iterations=3,
                ),
            )

        monkeypatch.setattr(
            diagnosis_router_module, "get_latest_diagnosis", fake_latest
        )
        resp = auth_client.get("/api/student/diagnosis")
        assert resp.status_code == 200
        assert resp.json()["data"] == {
            "alpha_vector": {"kp_001": 0.9},
            "diagnosed_at": "2026-10-05T10:00:00",
            "trace": {
                "algorithm_version": "dina-v1",
                "parameter_version": "default-v1",
                "answer_count": 2,
                "answer_time_from": "2026-10-01T10:00:00",
                "answer_time_to": "2026-10-05T09:00:00",
                "repeat_strategy": "latest_attempt",
                "converged": True,
                "iterations": 3,
            },
        }

    def test_latest_diagnosis_empty_is_success(self, monkeypatch, auth_client):
        """没有历史诊断时返回 data:null，页面可展示数据不足原因。"""
        async def fake_latest(user_id):
            return None

        monkeypatch.setattr(
            diagnosis_router_module, "get_latest_diagnosis", fake_latest
        )
        resp = auth_client.get("/api/student/diagnosis")
        assert resp.status_code == 200
        assert resp.json() == {"code": 0, "data": None, "message": "查询成功"}
