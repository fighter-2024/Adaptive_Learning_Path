"""
学习路径推荐单元测试

测试覆盖（不依赖真实 Neo4j / SQL Server / 大模型，可在任何环境运行）：
- 拓扑排序纯函数：前置不违反、环检测、子图外边的忽略
- 多指标贪心打分：掌握缺口/难度/时长/距离四项指标的单调性
- reason 生成：各分支文案（对照契约「2.4 学习路径」示例）
- 目标距离计算：直接前置距离为 1，不可达节点被排除
- 贪心选择：前置关系不被违反、已掌握排除、步数上限、目标模式只取可达节点
- 推荐/解释服务聚合逻辑（mock 同步 DB 函数与 LLM）
- 大模型封装：未配置时返回 None（降级触发）
- Pydantic 响应模型字段与 API 契约一致
- 路由注册正确性 + 数据库不可用时的统一响应格式（{code, data, message}）
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.learning_path import (
    LearningPathData,
    PathExplainData,
    PathStep,
)
from app.services.learning_path_service import (
    KnowledgeGraphCycleError,
    TargetNotFoundError,
    build_reason,
    build_rule_based_explanation,
    compute_distances_to_target,
    compute_greedy_score,
    explain_path,
    greedy_select_path,
    recommend_path,
    topological_sort,
)
from app.services.llm_service import chat_completion


def sample_topology():
    """示例图谱：kp_000 → kp_001 → {kp_002 → kp_003 → kp_005, kp_004(叶子)}"""
    return {
        "kp_000": {
            "name": "一元一次方程",
            "difficulty": 0.2,
            "estimated_time": 20,
            "successors": ["kp_001"],
        },
        "kp_001": {
            "name": "一元二次方程的定义",
            "difficulty": 0.3,
            "estimated_time": 25,
            "successors": ["kp_002", "kp_004"],
        },
        "kp_002": {
            "name": "配方法解一元二次方程",
            "difficulty": 0.5,
            "estimated_time": 30,
            "successors": ["kp_003"],
        },
        "kp_003": {
            "name": "求根公式推导",
            "difficulty": 0.6,
            "estimated_time": 40,
            "successors": ["kp_005"],
        },
        "kp_004": {
            "name": "韦达定理",
            "difficulty": 0.55,
            "estimated_time": 35,
            "successors": [],
        },
        "kp_005": {
            "name": "求根公式应用",
            "difficulty": 0.7,
            "estimated_time": 45,
            "successors": [],
        },
    }


def sample_mastery():
    """示例掌握数据：kp_000 已掌握，其余未掌握（kp_004 无记录）"""
    return {
        "kp_000": 0.9,
        "kp_001": 0.78,
        "kp_002": 0.45,
        "kp_003": 0.2,
        "kp_005": 0.1,
    }


class TestTopologicalSort:
    """拓扑排序（确保前置关系不违反 + 环检测）"""

    def test_linear_chain_keeps_order(self):
        """线性链拓扑序即原始顺序"""
        nodes = ["kp_000", "kp_001", "kp_002"]
        edges = [("kp_000", "kp_001"), ("kp_001", "kp_002")]
        assert topological_sort(nodes, edges) == ["kp_000", "kp_001", "kp_002"]

    def test_prerequisites_always_before_successors(self):
        """任意 DAG：每个边的后置都排在其前置之后"""
        nodes = ["kp_000", "kp_001", "kp_002", "kp_003", "kp_004", "kp_005"]
        edges = [
            ("kp_000", "kp_001"),
            ("kp_001", "kp_002"),
            ("kp_001", "kp_004"),
            ("kp_002", "kp_003"),
            ("kp_003", "kp_005"),
        ]
        order = topological_sort(nodes, edges)
        positions = {node: index for index, node in enumerate(order)}
        for source, target in edges:
            assert positions[source] < positions[target]

    def test_cycle_raises(self):
        """存在环时抛出 KnowledgeGraphCycleError"""
        with pytest.raises(KnowledgeGraphCycleError):
            topological_sort(
                ["kp_001", "kp_002"], [("kp_001", "kp_002"), ("kp_002", "kp_001")]
            )

    def test_self_loop_raises(self):
        """自环同样被检测"""
        with pytest.raises(KnowledgeGraphCycleError):
            topological_sort(["kp_001"], [("kp_001", "kp_001")])

    def test_edges_outside_subgraph_ignored(self):
        """子图外的边被忽略，不影响排序"""
        order = topological_sort(
            ["kp_002", "kp_003"],
            [("kp_002", "kp_003"), ("kp_999", "kp_002"), ("kp_003", "kp_998")],
        )
        assert order == ["kp_002", "kp_003"]


class TestComputeDistances:
    """目标距离计算（BFS，沿 前置→后继 方向反向）"""

    def test_distances_from_target(self):
        """目标自身为 0，前置为 1，前置的前置为 2……"""
        prereqs = {
            "kp_005": ["kp_003"],
            "kp_003": ["kp_002"],
            "kp_002": ["kp_001"],
            "kp_001": ["kp_000"],
        }
        distances = compute_distances_to_target("kp_005", prereqs)
        assert distances == {
            "kp_005": 0,
            "kp_003": 1,
            "kp_002": 2,
            "kp_001": 3,
            "kp_000": 4,
        }

    def test_unreachable_nodes_excluded(self):
        """无法到达目标的知识点不在结果中"""
        prereqs = {"kp_005": ["kp_003"], "kp_003": ["kp_002"]}
        distances = compute_distances_to_target("kp_005", prereqs)
        assert "kp_999" not in distances


class TestGreedyScore:
    """多指标贪心打分（四项指标单调性）"""

    def test_lower_mastery_scores_higher(self):
        """掌握缺口：概率越低分数越高"""
        low = compute_greedy_score(0.2, 0.5, 30, None, 1, 60)
        high = compute_greedy_score(0.8, 0.5, 30, None, 1, 60)
        assert low > high

    def test_none_mastery_treated_as_zero(self):
        """无诊断数据按 p=0 处理（缺口最大）"""
        assert compute_greedy_score(None, 0.5, 30, None, 1, 60) == compute_greedy_score(
            0.0, 0.5, 30, None, 1, 60
        )

    def test_easier_scores_higher(self):
        """难度越低分数越高"""
        easy = compute_greedy_score(0.5, 0.2, 30, None, 1, 60)
        hard = compute_greedy_score(0.5, 0.8, 30, None, 1, 60)
        assert easy > hard

    def test_shorter_time_scores_higher(self):
        """预估时长越短分数越高"""
        short = compute_greedy_score(0.5, 0.5, 10, None, 1, 60)
        long = compute_greedy_score(0.5, 0.5, 50, None, 1, 60)
        assert short > long

    def test_closer_to_target_scores_higher(self):
        """距目标越近分数越高（目标模式）"""
        near = compute_greedy_score(0.5, 0.5, 30, 1, 4, 60)
        far = compute_greedy_score(0.5, 0.5, 30, 4, 4, 60)
        assert near > far

    def test_global_mode_ignores_distance(self):
        """全局模式（distance=None）距离项不参与：相同输入分数一致"""
        score_a = compute_greedy_score(0.5, 0.5, 30, None, 1, 60)
        score_b = compute_greedy_score(0.5, 0.5, 30, None, 99, 60)
        assert score_a == score_b


class TestBuildReason:
    """单步推荐理由生成（文案对照契约示例）"""

    @pytest.mark.parametrize(
        "mastery, expected",
        [
            (0.78, "当前掌握 78%，巩固后可进入下一阶段"),
            (0.45, "当前掌握 45%，巩固后可进入下一阶段"),
            (0.39, "当前掌握 39%，基础薄弱，需重点学习"),
            (0.2, "当前掌握 20%，基础薄弱，需重点学习"),
            (None, "尚未开始学习，建议从基础概念入手"),
        ],
    )
    def test_mastery_based_reasons(self, mastery, expected):
        """按掌握概率分档生成理由"""
        assert build_reason(mastery, False, None, None, []) == expected

    def test_target_reason(self):
        """目标知识点专用文案"""
        assert (
            build_reason(0.3, True, 0, "求根公式应用", [])
            == "这是你的目标知识点，建议集中精力学习"
        )

    def test_pending_prereq_reason(self):
        """前置已入路径但未掌握 → 对照契约示例步骤 2 文案"""
        assert (
            build_reason(0.45, False, 2, None, ["配方法解一元二次方程"])
            == "前置知识「配方法解一元二次方程」尚未完全掌握，需重点学习"
        )

    def test_direct_prereq_suffix(self):
        """距目标 1 跳时追加「直接前置」说明"""
        assert (
            build_reason(0.2, False, 1, "求根公式应用", [])
            == "当前掌握 20%，基础薄弱，需重点学习，是目标「求根公式应用」的直接前置"
        )


class TestGreedySelect:
    """贪心选择：拓扑约束 + 排除已掌握 + 步数上限"""

    def _prereqs_map(self, topology):
        result = {kp_id: [] for kp_id in topology}
        for kp_id, attrs in topology.items():
            for successor in attrs["successors"]:
                result[successor].append(kp_id)
        return result

    def test_target_mode_chain_to_target(self):
        """目标模式：只推通往目标的链，叶子 kp_004 被排除"""
        topology = sample_topology()
        candidates = ["kp_001", "kp_002", "kp_003", "kp_005"]
        steps = greedy_select_path(
            candidates=candidates,
            prereqs_map=self._prereqs_map(topology),
            mastery_map=sample_mastery(),
            node_attrs=topology,
            dist_map={"kp_005": 0, "kp_003": 1, "kp_002": 2, "kp_001": 3},
            target_id="kp_005",
            target_name="求根公式应用",
            count=5,
        )
        assert [step["id"] for step in steps] == [
            "kp_001",
            "kp_002",
            "kp_003",
            "kp_005",
        ]
        # 每一步的前置要么已掌握、要么已出现在更早的步骤里
        selected = set()
        for step in steps:
            for prereq in self._prereqs_map(topology).get(step["id"], []):
                assert prereq in selected or sample_mastery().get(prereq, 0) >= 0.8
            selected.add(step["id"])
        # 目标步的 reason 是目标文案；直接前置步带「直接前置」说明
        assert steps[3]["reason"] == "这是你的目标知识点，建议集中精力学习"
        assert "直接前置" in steps[2]["reason"]

    def test_count_cap(self):
        """步数上限生效（count 小于候选数时截断）"""
        topology = sample_topology()
        candidates = ["kp_001", "kp_002", "kp_003", "kp_005"]
        steps = greedy_select_path(
            candidates=candidates,
            prereqs_map=self._prereqs_map(topology),
            mastery_map=sample_mastery(),
            node_attrs=topology,
            dist_map=None,
            target_id=None,
            target_name=None,
            count=2,
        )
        assert len(steps) == 2

    def test_mastered_excluded_by_caller_not_reselected(self):
        """候选外的前置即使未入选路径，只要已掌握也视为满足（可继续推进）"""
        topology = sample_topology()
        steps = greedy_select_path(
            candidates=["kp_001", "kp_002", "kp_003", "kp_005"],
            prereqs_map=self._prereqs_map(topology),
            mastery_map=sample_mastery(),  # kp_000=0.9 已掌握，不在候选内
            node_attrs=topology,
            dist_map=None,
            target_id=None,
            target_name=None,
            count=5,
        )
        # kp_001 的前置 kp_000 已掌握（不在候选），因此 kp_001 可直接入选
        assert steps[0]["id"] == "kp_001"

    def test_order_and_fields(self):
        """步骤字典字段完整：order 从 1 递增，含 reason 等全部契约字段"""
        topology = sample_topology()
        steps = greedy_select_path(
            candidates=["kp_001"],
            prereqs_map=self._prereqs_map(topology),
            mastery_map=sample_mastery(),
            node_attrs=topology,
            dist_map=None,
            target_id=None,
            target_name=None,
            count=5,
        )
        assert set(steps[0].keys()) == {
            "order",
            "id",
            "name",
            "reason",
            "difficulty",
            "estimated_time",
            "mastery_probability",
        }
        assert steps[0]["order"] == 1
        assert steps[0]["reason"]


class TestRecommendPathService:
    """推荐服务聚合逻辑（mock 同步 DB 函数）"""

    @pytest.fixture(autouse=True)
    def _mock_db(self, monkeypatch):
        """默认 mock Neo4j 拓扑与 SQL Server 掌握数据"""
        monkeypatch.setattr(
            "app.services.learning_path_service._db_load_topology",
            lambda: sample_topology(),
        )
        monkeypatch.setattr(
            "app.services.learning_path_service._db_query_mastery_map",
            lambda user_id, kp_ids: {
                kp_id: sample_mastery()[kp_id]
                for kp_id in kp_ids
                if kp_id in sample_mastery()
            },
        )

    def test_target_mode_returns_path_with_target(self):
        """目标模式：target 正确、步骤均为通往目标的知识点"""
        data = asyncio.run(recommend_path("stu_001", "kp_005", 5))
        assert isinstance(data, LearningPathData)
        assert data.target is not None
        assert data.target.id == "kp_005"
        assert data.target.name == "求根公式应用"
        assert [step.knowledge_point.id for step in data.steps] == [
            "kp_001",
            "kp_002",
            "kp_003",
            "kp_005",
        ]
        # 每步含 reason，且已掌握知识点不出现
        for step in data.steps:
            assert step.reason
            assert step.knowledge_point.id != "kp_000"
        assert data.steps[0].mastery_probability == 0.78

    def test_global_mode_returns_steps_without_target(self):
        """全局模式：target 为 None，推荐全局下一步序列"""
        data = asyncio.run(recommend_path("stu_001", None, 5))
        assert data.target is None
        assert len(data.steps) == 5
        assert [step.order for step in data.steps] == [1, 2, 3, 4, 5]
        # 前置关系不被违反：每步前置要么已掌握、要么出现在更早步骤
        topology = sample_topology()
        prereqs_map = {}
        for kp_id, attrs in topology.items():
            for successor in attrs["successors"]:
                prereqs_map.setdefault(successor, []).append(kp_id)
        selected = set()
        for step in data.steps:
            for prereq in prereqs_map.get(step.knowledge_point.id, []):
                assert prereq in selected or sample_mastery().get(prereq, 0) >= 0.8
            selected.add(step.knowledge_point.id)

    def test_anonymous_all_not_started(self):
        """匿名视角：掌握概率全部为 None，reason 为未开始文案"""
        data = asyncio.run(recommend_path(None, None, 5))
        assert len(data.steps) == 5
        assert all(step.mastery_probability is None for step in data.steps)
        assert data.steps[0].reason == "尚未开始学习，建议从基础概念入手"

    def test_target_not_found_raises(self):
        """目标知识点不存在 → TargetNotFoundError（router 映射 40400）"""
        with pytest.raises(TargetNotFoundError):
            asyncio.run(recommend_path("stu_001", "kp_999", 5))

    def test_sql_failure_degrades_to_not_started(self, monkeypatch):
        """SQL Server 异常降级：全部按未开始处理，接口不中断"""

        def boom(user_id, kp_ids):
            raise RuntimeError("sql down")

        monkeypatch.setattr(
            "app.services.learning_path_service._db_query_mastery_map", boom
        )
        data = asyncio.run(recommend_path("stu_001", None, 3))
        assert len(data.steps) == 3
        assert all(step.mastery_probability is None for step in data.steps)

    def test_all_mastered_returns_empty_steps(self, monkeypatch):
        """全部掌握时不推荐任何步骤"""
        monkeypatch.setattr(
            "app.services.learning_path_service._db_query_mastery_map",
            lambda user_id, kp_ids: {
                kp_id: 0.95 for kp_id in kp_ids if kp_id in sample_topology()
            },
        )
        data = asyncio.run(recommend_path("stu_001", None, 5))
        assert data.steps == []

    def test_cycle_raises(self, monkeypatch):
        """图谱存在环 → KnowledgeGraphCycleError（router 映射 50002）"""
        cyclic = {
            "kp_001": {
                "name": "A",
                "difficulty": 0.3,
                "estimated_time": 10,
                "successors": ["kp_002"],
            },
            "kp_002": {
                "name": "B",
                "difficulty": 0.3,
                "estimated_time": 10,
                "successors": ["kp_001"],
            },
        }
        monkeypatch.setattr(
            "app.services.learning_path_service._db_load_topology", lambda: cyclic
        )
        with pytest.raises(KnowledgeGraphCycleError):
            asyncio.run(recommend_path("stu_001", None, 5))


class TestExplainService:
    """路径解释服务（LLM 优先 + 降级）"""

    @pytest.fixture(autouse=True)
    def _mock_db(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.learning_path_service._db_load_topology",
            lambda: sample_topology(),
        )
        monkeypatch.setattr(
            "app.services.learning_path_service._db_query_mastery_map",
            lambda user_id, kp_ids: {
                kp_id: sample_mastery()[kp_id]
                for kp_id in kp_ids
                if kp_id in sample_mastery()
            },
        )

    def test_explain_uses_llm_when_available(self, monkeypatch):
        """大模型可用时使用其输出"""

        async def fake_chat(messages, temperature=0.7, max_tokens=1024):
            return "大模型生成的解释"

        monkeypatch.setattr(
            "app.services.learning_path_service.chat_completion", fake_chat
        )
        explanation = asyncio.run(explain_path("stu_001", "kp_005", 5))
        assert explanation == "大模型生成的解释"

    def test_explain_falls_back_when_llm_fails(self, monkeypatch):
        """大模型失败（返回 None）时降级为规则解释，且提及路径步骤"""

        async def fake_chat(messages, temperature=0.7, max_tokens=1024):
            return None

        monkeypatch.setattr(
            "app.services.learning_path_service.chat_completion", fake_chat
        )
        explanation = asyncio.run(explain_path("stu_001", "kp_005", 5))
        assert explanation  # 非空
        assert "求根公式应用" in explanation  # 提及目标
        assert "一元二次方程的定义" in explanation  # 提及路径首步
        assert "分钟" in explanation

    def test_explain_falls_back_when_llm_too_long(self, monkeypatch):
        """大模型输出超长 → 视为异常输出，降级为规则解释"""

        async def fake_chat(messages, temperature=0.7, max_tokens=1024):
            return "很" * 3000

        monkeypatch.setattr(
            "app.services.learning_path_service.chat_completion", fake_chat
        )
        explanation = asyncio.run(explain_path("stu_001", "kp_005", 5))
        assert len(explanation) <= 2000

    def test_explain_falls_back_when_llm_raises(self, monkeypatch):
        """大模型调用抛异常（双保险）→ 降级为规则解释"""

        async def boom(messages, temperature=0.7, max_tokens=1024):
            raise RuntimeError("llm down")

        monkeypatch.setattr(
            "app.services.learning_path_service.chat_completion", boom
        )
        explanation = asyncio.run(explain_path("stu_001", "kp_005", 5))
        assert explanation

    def test_rule_based_explanation_empty_steps(self):
        """无步骤时给出友好的降级文案"""
        data = LearningPathData(target=None, steps=[])
        explanation = build_rule_based_explanation(data)
        assert explanation


class TestLlmService:
    """统一大模型封装（总则第八章）"""

    def test_chat_completion_returns_none_when_unconfigured(self, monkeypatch):
        """未配置密钥/接口地址时直接返回 None（触发调用方降级）"""
        monkeypatch.setattr("app.services.llm_service.settings.LLM_API_KEY", "")
        monkeypatch.setattr("app.services.llm_service.settings.LLM_API_BASE", "")
        result = asyncio.run(
            chat_completion([{"role": "user", "content": "你好"}])
        )
        assert result is None


class TestLearningPathModels:
    """Pydantic 响应模型（严格对照契约 2.4）"""

    def test_step_fields_match_contract(self):
        """步骤字段与契约一致（order/knowledge_point/reason/difficulty/
        estimated_time/mastery_probability）"""
        step = PathStep(
            order=1,
            knowledge_point={"id": "kp_002", "name": "配方法解一元二次方程"},
            reason="当前掌握 78%，巩固后可进入下一阶段",
            difficulty=0.5,
            estimated_time=30,
            mastery_probability=0.78,
        )
        dumped = step.model_dump()
        assert set(dumped.keys()) == {
            "order",
            "knowledge_point",
            "reason",
            "difficulty",
            "estimated_time",
            "mastery_probability",
        }
        assert set(dumped["knowledge_point"].keys()) == {"id", "name"}

    def test_path_data_fields_match_contract(self):
        """路径 data 字段与契约一致（target/steps）"""
        data = LearningPathData(
            target={"id": "kp_005", "name": "求根公式应用"}, steps=[]
        )
        assert set(data.model_dump().keys()) == {"target", "steps"}

    def test_path_data_defaults_for_global_mode(self):
        """全局模式：target 默认 None"""
        data = LearningPathData()
        assert data.target is None
        assert data.steps == []

    def test_explain_data_fields_match_contract(self):
        """解释 data 字段与契约一致（explanation）"""
        data = PathExplainData(explanation="根据你的诊断结果……")
        assert set(data.model_dump().keys()) == {"explanation"}


class TestRoutes:
    """路由注册与统一响应格式（mock Neo4j 不可用，不依赖真实数据库）"""

    @pytest.fixture
    def client(self, monkeypatch):
        """mock get_driver：立即抛出 ServiceUnavailable，验证错误处理路径"""
        from neo4j.exceptions import ServiceUnavailable

        def boom_driver():
            raise ServiceUnavailable("Neo4j unavailable (test mock)")

        monkeypatch.setattr(
            "app.services.learning_path_service.get_driver", boom_driver
        )
        return TestClient(app)

    @pytest.mark.parametrize(
        "path",
        ["/api/student/path", "/api/student/path/explain"],
    )
    def test_routes_registered_not_404(self, client, path):
        """两个接口均已注册（不返回 404；Neo4j 不可用时返回业务码而非路由不存在）"""
        resp = client.get(path)
        assert resp.status_code != 404
        body = resp.json()
        assert set(body.keys()) == {"code", "data", "message"}

    def test_path_returns_unified_error_when_neo4j_down(self, client):
        """Neo4j 不可用时 /path 返回统一错误响应（业务码 50002，不抛裸异常）"""
        resp = client.get("/api/student/path")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 50002
        assert body["data"] is None
        assert body["message"] == "图数据库异常，请稍后重试"

    def test_explain_returns_unified_error_when_neo4j_down(self, client):
        """Neo4j 不可用时 /path/explain 返回统一错误响应（业务码 50002）"""
        resp = client.get("/api/student/path/explain")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 50002
        assert body["data"] is None

    def test_invalid_count_rejected_by_validation(self, client):
        """count=0 触发 Pydantic 参数校验（ge=1）→ HTTP 422 + 业务码 40000"""
        resp = client.get("/api/student/path", params={"count": 0})
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == 40000

    def test_invalid_token_falls_back_to_anonymous(self, client):
        """无效 Token 时可选身份解析降级为匿名，接口不因认证失败返回 401"""
        resp = client.get(
            "/api/student/path",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # Neo4j 被 mock 为不可用，说明身份解析已成功降级并继续走业务逻辑
        assert body["code"] == 50002
