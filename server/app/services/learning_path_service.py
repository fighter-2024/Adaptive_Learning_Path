"""
学习路径推荐业务服务

严格对照 docs/API契约文档.md「2.4 学习路径」：
- GET /api/student/path         推荐学习序列（data: {target, steps}，每步含 reason）
- GET /api/student/path/explain 路径推荐的 AI 通俗解释（含降级元数据）

数据职责（AI开发总则第六条「数据库职责划分」）：
- 知识点节点属性 + PREREQUISITE 前置关系 → Neo4j（图谱拓扑）
- 学员掌握概率快照 user_kp_mastery    → SQL Server（DINA 诊断结果）

推荐算法（总则第一章「核心能力」：拓扑排序 + 多指标贪心推荐）：
1. 从 Neo4j 一次性加载全部知识点节点与前置边（知识点通常为百级规模）；
2. Kahn 拓扑排序候选子图，检测环（有环说明图谱数据异常，抛错由 router 映射）；
3. 多指标贪心打分，分数越高越优先：
       score = W_掌握缺口·(1-p) + W_难度·(1-difficulty)
             + W_时长·(1-t/t_max) + W_距离·(1-dist/dist_max)
   - 掌握缺口 1-p：p 越低越优先（弱项优先补），无诊断数据按 p=0 处理；
   - 难度 1-difficulty：越简单越优先（循序渐进，难度 0.0~1.0）；
   - 时长 1-t/t_max：预估耗时越短越优先（t_max 为候选内最大时长）；
   - 距离 1-dist/dist_max：距目标跳数越少越优先（仅目标模式参与打分）。
4. 贪心选择：每一步只在「前置已满足」的候选里选分最高者——前置已满足
   指前置知识点已掌握（p≥0.8）或已入选当前路径；因此产出序列天然满足
   拓扑序，前置关系不被违反；
5. 每步生成可读 reason（文案风格对照契约示例）。

AI 解释（总则第八章「AI 大模型调用规范」）：
- 大模型调用统一走 app.services.llm_service（超时 30s、最多重试 2 次）；
- Prompt 模板集中在 app.config.prompts，不硬编码在业务逻辑里；
- 大模型输出做非空/长度校验，失败时降级为规则拼装的通俗解释，
  不阻塞业务流程。

Service 层不接触 HTTP 对象，只处理业务数据；所有同步 Neo4j / SQL Server
操作通过 asyncio.to_thread 放入线程池执行，避免阻塞事件循环。
"""

import asyncio
import logging
from collections import deque
from typing import Dict, List, Optional, Tuple

from app.config.prompts import (
    PATH_EXPLAIN_SYSTEM_PROMPT,
    build_path_explain_user_prompt,
)
from app.db import get_driver
from app.models.learning_path import LearningPathData, PathExplainData, PathStep, PathTarget
from app.services.config_service import PathAlgorithmConfig, get_path_algorithm_config
from app.services.llm_service import chat_completion

logger = logging.getLogger(__name__)

# ==================== 算法参数（业务可调，改动需同步测试） ====================

MASTERED_THRESHOLD = 0.8  # 掌握阈值，与契约「2.1 学习」mastered ≥ 0.8 一致

# 大模型解释的长度上限（总则：大模型返回内容必须做长度校验）
MAX_EXPLAIN_LENGTH = 2000


# ==================== 业务异常 ====================
# Router 层捕获这些异常并映射为统一响应码，不向客户端暴露内部堆栈。


class KnowledgeGraphCycleError(Exception):
    """知识图谱前置关系存在环路（拓扑排序检测失败）"""


class TargetNotFoundError(Exception):
    """目标知识点不存在"""

    def __init__(self, kp_id: str) -> None:
        self.kp_id = kp_id
        super().__init__(f"目标知识点 {kp_id} 不存在")


# ==================== 纯函数工具（便于单元测试） ====================


def topological_sort(nodes: List[str], edges: List[Tuple[str, str]]) -> List[str]:
    """Kahn 拓扑排序（纯函数）

    边语义：(前置, 后继)，即前置知识点必须排在后继知识点之前。
    不在 nodes 中的边端点会被忽略（用于对候选子图排序）。
    同批入度为 0 的节点按 nodes 中出现的先后顺序出队，结果稳定可复现。

    Args:
        nodes: 节点 ID 列表（出现顺序作为同批次出队顺序）
        edges: (前置, 后继) 边列表

    Returns:
        拓扑排序后的节点 ID 列表，任意边的后置都排在其前置之后

    Raises:
        KnowledgeGraphCycleError: 图中存在环，无法拓扑排序
    """
    node_set = set(nodes)
    indegree: Dict[str, int] = {n: 0 for n in nodes}
    adjacency: Dict[str, List[str]] = {n: [] for n in nodes}
    for source, target in edges:
        if source not in node_set or target not in node_set:
            continue  # 忽略子图外的边
        adjacency[source].append(target)
        indegree[target] += 1

    queue = deque(n for n in nodes if indegree[n] == 0)
    result: List[str] = []
    while queue:
        current = queue.popleft()
        result.append(current)
        for successor in adjacency[current]:
            indegree[successor] -= 1
            if indegree[successor] == 0:
                queue.append(successor)

    if len(result) != len(nodes):
        involved = sorted(set(nodes) - set(result))
        raise KnowledgeGraphCycleError(
            "知识图谱前置关系存在环路，涉及知识点: " + ", ".join(involved[:5])
        )
    return result


def compute_distances_to_target(
    target_id: str, prereqs_map: Dict[str, List[str]]
) -> Dict[str, int]:
    """计算各知识点到目标知识点的最短跳数（纯函数）

    沿 前置→后继 方向从目标反向 BFS：distance=1 表示该知识点是目标的
    直接前置。无法到达目标的知识点不出现在结果中（目标模式会将其排除）。

    Args:
        target_id: 目标知识点 ID
        prereqs_map: {知识点 ID: 前置知识点 ID 列表}

    Returns:
        {知识点 ID: 距目标跳数}，目标自身为 0
    """
    distances: Dict[str, int] = {target_id: 0}
    queue = deque([target_id])
    while queue:
        current = queue.popleft()
        for prerequisite in prereqs_map.get(current, []):
            if prerequisite not in distances:
                distances[prerequisite] = distances[current] + 1
                queue.append(prerequisite)
    return distances


def compute_greedy_score(
    mastery: Optional[float],
    difficulty: float,
    estimated_time: int,
    distance_to_target: Optional[int],
    max_distance: int,
    max_time: int,
    config: Optional[PathAlgorithmConfig] = None,
) -> float:
    """多指标贪心打分（纯函数），分数越高越优先

    四项指标：
    - 掌握缺口 1-p：p 越低越优先；None（无诊断数据）按 p=0 处理；
    - 难度 1-difficulty：越简单越优先（循序渐进）；
    - 时长 1-t/t_max：预估耗时越短越优先；max_time=0 时该项计满分；
    - 距离 1-dist/dist_max：距目标越近越优先；仅目标模式参与。

    Args:
        mastery: 当前掌握概率 0.0~1.0；None 表示无诊断数据
        difficulty: 难度系数 0.0~1.0
        estimated_time: 预估学习时长（分钟）
        distance_to_target: 距目标跳数；None 表示全局模式（无目标）
        max_distance: 候选内最大距离（归一化用，>0）
        max_time: 候选内最大预估时长（归一化用）

    Returns:
        综合得分，范围约 0.0~1.0
    """
    return compute_score_components(
        mastery=mastery,
        difficulty=difficulty,
        estimated_time=estimated_time,
        distance_to_target=distance_to_target,
        max_distance=max_distance,
        max_time=max_time,
        config=config,
    )["total"]


def compute_score_components(
    mastery: Optional[float],
    difficulty: float,
    estimated_time: int,
    distance_to_target: Optional[int],
    max_distance: int,
    max_time: int,
    config: Optional[PathAlgorithmConfig] = None,
) -> Dict[str, float]:
    """计算各指标的加权得分，返回值直接用于 V2 ``score_components``。

    ``None`` 掌握度继续按 0 计算以保持历史排序行为；调用方通过 ``meta``
    的 ``mastery_source``/``degraded`` 明确说明这不是可靠的个性化掌握数据。
    """
    algorithm_config = config or get_path_algorithm_config()
    probability = mastery if mastery is not None else 0.0
    gap_score = max(0.0, min(1.0, 1.0 - probability))
    difficulty_score = max(0.0, min(1.0, 1.0 - difficulty))
    time_score = max(
        0.0,
        min(1.0, 1.0 - (estimated_time / max_time if max_time > 0 else 0.0)),
    )
    distance_score = (
        max(0.0, min(1.0, 1.0 - (distance_to_target / max_distance)))
        if distance_to_target is not None and max_distance > 0
        else (1.0 if distance_to_target is not None else 0.0)
    )
    components = {
        "mastery": algorithm_config.mastery * gap_score,
        "target_distance": algorithm_config.target_distance * distance_score,
        "difficulty": algorithm_config.difficulty * difficulty_score,
        "time_cost": algorithm_config.time_cost * time_score,
    }
    components["total"] = sum(components.values())
    return components


def build_reason_codes(
    mastery: Optional[float],
    is_target: bool,
    distance_to_target: Optional[int],
    pending_prereq_names: List[str],
    mastery_source: str = "available",
) -> List[str]:
    """生成机器可读推荐原因，顺序稳定且不暴露内部异常。"""
    codes: List[str] = []
    if mastery_source == "unavailable":
        codes.append("MASTERY_DATA_UNAVAILABLE")
    elif mastery is None:
        codes.append("NO_MASTERY_DATA")
    elif mastery < 0.4:
        codes.append("LOW_MASTERY")
    elif mastery < MASTERED_THRESHOLD:
        codes.append("NEEDS_REVIEW")
    if pending_prereq_names:
        codes.append("PREREQUISITE_PENDING")
    if distance_to_target == 1:
        codes.append("TARGET_PREREQUISITE")
    if is_target:
        codes.append("TARGET_KNOWLEDGE_POINT")
    return codes


def _mastery_status(mastery: Optional[float]) -> str:
    """将掌握概率映射为契约定义的学生端状态。"""
    if mastery is None:
        return "not_started"
    if mastery >= MASTERED_THRESHOLD:
        return "mastered"
    if mastery >= 0.4:
        return "learning"
    return "weak"


def build_reason(
    mastery: Optional[float],
    is_target: bool,
    distance_to_target: Optional[int],
    target_name: Optional[str],
    pending_prereq_names: List[str],
    mastery_source: str = "available",
) -> str:
    """生成单步推荐理由（纯函数），文案风格对照契约「2.4 学习路径」示例

    规则优先级：
    1. 本步是目标知识点 → 「这是你的目标知识点，建议集中精力学习」；
    2. 有前置知识点已入选路径但尚未掌握（<0.8）→ 「前置知识…尚未完全掌握，
       需重点学习」（对照契约示例步骤 2 的文案）；
    3. 无诊断数据 → 「尚未开始学习，建议从基础概念入手」；
    4. 掌握概率 <0.4 → 「当前掌握 X%，基础薄弱，需重点学习」；
    5. 其余（0.4~0.8）→ 「当前掌握 X%，巩固后可进入下一阶段」。
    非目标步且距目标 1 跳时追加「，是目标「XX」的直接前置」。

    Args:
        mastery: 当前掌握概率；None 表示无诊断数据
        is_target: 本步是否为目标知识点
        distance_to_target: 距目标跳数；None 表示全局模式
        target_name: 目标知识点名称（生成直接前置说明用）
        pending_prereq_names: 已入选路径但尚未掌握的前置知识点名称列表

    Returns:
        面向学生的中文推荐理由
    """
    if mastery_source == "unavailable":
        reason = "掌握数据暂不可用，本步依据知识图谱与学习成本推荐"
    elif is_target:
        reason = "这是你的目标知识点，建议集中精力学习"
    elif pending_prereq_names:
        reason = (
            "前置知识「" + "、".join(pending_prereq_names) + "」尚未完全掌握，需重点学习"
        )
    elif mastery is None:
        reason = "尚未开始学习，建议从基础概念入手"
    elif mastery < 0.4:
        reason = f"当前掌握 {mastery:.0%}，基础薄弱，需重点学习"
    else:
        reason = f"当前掌握 {mastery:.0%}，巩固后可进入下一阶段"

    if not is_target and distance_to_target == 1 and target_name:
        reason += f"，是目标「{target_name}」的直接前置"
    return reason


def greedy_select_path(
    candidates: List[str],
    prereqs_map: Dict[str, List[str]],
    mastery_map: Dict[str, float],
    node_attrs: Dict[str, dict],
    dist_map: Optional[Dict[str, int]],
    target_id: Optional[str],
    target_name: Optional[str],
    count: int,
    config: Optional[PathAlgorithmConfig] = None,
    mastery_source: str = "available",
) -> List[dict]:
    """多指标贪心选择学习路径（纯函数，便于单元测试）

    每一步只在「前置已满足」的候选里选分最高者：
    - 前置已掌握（掌握概率 ≥ MASTERED_THRESHOLD）；
    - 或前置已入选当前路径。
    因此返回序列满足拓扑序，前置关系不被违反；分数相同时按
    candidates 给出的拓扑序取先出现者，结果稳定可复现。

    Args:
        candidates: 候选知识点 ID 列表（必须已按拓扑序排列）
        prereqs_map: {知识点 ID: 前置知识点 ID 列表}
        mastery_map: {知识点 ID: 掌握概率}；无记录的 ID 不在结果中
        node_attrs: {知识点 ID: {name, difficulty, estimated_time}}
        dist_map: {知识点 ID: 距目标距离}；None 表示全局模式
        target_id: 目标知识点 ID；None 表示全局模式
        target_name: 目标知识点名称（生成 reason 用）
        count: 推荐步数上限

    Returns:
        步骤字典列表，包含兼容字段和 V2 的 reason_codes、score_components。
    """
    mastered = {
        kp_id
        for kp_id, probability in mastery_map.items()
        if probability is not None and probability >= MASTERED_THRESHOLD
    }
    max_time = max(
        (node_attrs[n].get("estimated_time") or 0 for n in candidates), default=0
    )
    max_distance = max(dist_map.values(), default=0) if dist_map else 0

    remaining = list(candidates)
    selected_ids: List[str] = []
    steps: List[dict] = []

    while len(steps) < count and remaining:
        satisfiable = [
            n
            for n in remaining
            if all(p in mastered or p in selected_ids for p in prereqs_map.get(n, []))
        ]
        if not satisfiable:
            # 正常情况下不会走到这里（候选裁剪保证前置要么已掌握、
            # 要么也在候选内）；出现即图谱数据异常，停止推荐返回已选步骤
            logger.warning("贪心选择中断：无可满足前置的候选，已选 %d 步", len(steps))
            break

        best_id: Optional[str] = None
        best_score = float("-inf")
        for n in satisfiable:  # 按拓扑序遍历，分数相同时保留先出现者
            attrs = node_attrs[n]
            score = compute_greedy_score(
                mastery=mastery_map.get(n),
                difficulty=attrs.get("difficulty") or 0.0,
                estimated_time=attrs.get("estimated_time") or 0,
                distance_to_target=dist_map.get(n) if dist_map else None,
                max_distance=max_distance,
                max_time=max_time,
                config=config,
            )
            if score > best_score:
                best_id = n
                best_score = score

        # satisfiable 非空时 best_id 必被赋值；此处防御性断言
        if best_id is None:
            break

        remaining.remove(best_id)
        selected_ids.append(best_id)

        # 已入选路径且尚未掌握（<0.8 或未知）的前置知识点 → reason 需提示
        pending_prereq_names = [
            node_attrs[p]["name"]
            for p in prereqs_map.get(best_id, [])
            if p in selected_ids
            and (mastery_map.get(p) is None or mastery_map.get(p) < MASTERED_THRESHOLD)
        ]

        attrs = node_attrs[best_id]
        best_mastery = mastery_map.get(best_id)
        best_distance = dist_map.get(best_id) if dist_map else None
        is_target = target_id is not None and best_id == target_id
        score_components = compute_score_components(
            mastery=best_mastery,
            difficulty=attrs.get("difficulty") or 0.0,
            estimated_time=attrs.get("estimated_time") or 0,
            distance_to_target=best_distance,
            max_distance=max_distance,
            max_time=max_time,
            config=config,
        )

        steps.append(
            {
                "order": len(steps) + 1,
                "id": best_id,
                "name": node_attrs[best_id]["name"],
                "reason": build_reason(
                    mastery=best_mastery,
                    is_target=is_target,
                    distance_to_target=best_distance,
                    target_name=target_name,
                    pending_prereq_names=pending_prereq_names,
                    mastery_source=mastery_source,
                ),
                "difficulty": attrs.get("difficulty") or 0.0,
                "estimated_time": attrs.get("estimated_time") or 0,
                "mastery_probability": best_mastery,
                "status": _mastery_status(best_mastery),
                "locked": False,
                "reason_codes": build_reason_codes(
                    mastery=best_mastery,
                    is_target=is_target,
                    distance_to_target=best_distance,
                    pending_prereq_names=pending_prereq_names,
                    mastery_source=mastery_source,
                ),
                "score_components": score_components,
            }
        )

    return steps


def build_rule_based_explanation(data: LearningPathData) -> str:
    """规则拼装的路径通俗解释（大模型不可用时的降级内容）

    Args:
        data: 推荐路径数据

    Returns:
        面向学生的通俗解释文本（非空，保证接口始终返回可用内容）
    """
    if not data.steps:
        return "你已经掌握了这条路径上的全部知识点，暂时没有新的推荐内容，继续保持！"

    parts: List[str] = []
    for step in data.steps:
        if step.difficulty < 0.4:
            difficulty_text = "难度较低"
        elif step.difficulty < 0.7:
            difficulty_text = "难度中等"
        else:
            difficulty_text = "难度较高"
        parts.append(
            f"第{step.order}步学习「{step.knowledge_point.name}」"
            f"（{difficulty_text}，约{step.estimated_time}分钟）"
        )

    total_minutes = sum(step.estimated_time for step in data.steps)
    if data.meta.degraded and data.meta.mastery_source == "unavailable":
        head = "由于当前掌握数据暂时不可用，先依据知识图谱与学习成本，"
    elif data.target:
        head = f"为了掌握「{data.target.name}」，"
    else:
        head = "根据你目前的掌握情况，"
    return (
        f"{head}建议按以下顺序学习：{'；'.join(parts)}。"
        f"全程预计约 {total_minutes} 分钟，建议每天安排 20~30 分钟，"
        "循序渐进，遇到困难不要跳过前置知识。"
    )


# ==================== Neo4j 同步操作（线程池执行） ====================


def _db_load_topology() -> Dict[str, dict]:
    """从 Neo4j 加载全部知识点拓扑（同步执行）

    一次查询取回全部节点属性与前置边，供路径算法在内存中计算
    （知识点规模通常为百级，单次加载可行）。历史导入数据可能缺
    difficulty / estimated_time 属性，给默认值保证计算不中断。

    Returns:
        {知识点 ID: {name, difficulty, estimated_time, successors}}，
        successors 为以该知识点为前置的后继知识点 ID 列表
    """
    driver = get_driver()
    with driver.session() as session:
        result = session.run(
            """
            MATCH (k:KnowledgePoint)
            OPTIONAL MATCH (k)-[:PREREQUISITE]->(s:KnowledgePoint)
            RETURN k.id AS id,
                   k.name AS name,
                   k.difficulty AS difficulty,
                   k.estimated_time AS estimated_time,
                   [x IN collect(DISTINCT s.id) WHERE x IS NOT NULL] AS successors
            ORDER BY k.id
            """
        )
        topology: Dict[str, dict] = {}
        for record in result:
            topology[record["id"]] = {
                "name": record["name"],
                "difficulty": record["difficulty"]
                if record["difficulty"] is not None
                else 0.0,
                "estimated_time": record["estimated_time"]
                if record["estimated_time"] is not None
                else 0,
                "successors": list(record["successors"]),
            }
    return topology


# ==================== SQL Server 同步操作（线程池执行） ====================


def _db_query_mastery_map(user_id: str, kp_ids: List[str]) -> Dict[str, float]:
    """从 user_kp_mastery 批量查询学员掌握概率（同步执行）

    掌握快照表职责见 docs/数据库设计.md「1.7 user_kp_mastery」：
    每次答题后实时更新，无记录即无数据（按未开始学习处理）。

    Args:
        user_id: 学生业务 ID
        kp_ids: 知识点 ID 列表

    Returns:
        {knowledge_point_id: mastery_probability}，无记录的 ID 不在结果中
    """
    if not kp_ids:
        return {}
    # 延迟导入避免模块循环依赖
    from app.db.sqlserver import get_connection

    placeholders = ", ".join(["?"] * len(kp_ids))
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT knowledge_point_id, mastery_probability FROM user_kp_mastery "
            f"WHERE user_id = ? AND knowledge_point_id IN ({placeholders})",
            (user_id, *kp_ids),
        )
        return {row[0]: float(row[1]) for row in cursor.fetchall()}
    finally:
        conn.close()


# ==================== 异步服务接口 ====================


async def recommend_path(
    user_id: Optional[str],
    target_kp_id: Optional[str],
    count: int = 5,
) -> LearningPathData:
    """推荐学习路径（目标模式 / 全局模式）

    目标模式（传 target_kp_id）：候选限定为「能够到达目标」的知识点，
    按多指标贪心推荐通往目标的下一步学习序列；
    全局模式（不传）：候选为全部未掌握知识点，推荐全局下一步序列。
    两种模式都经过拓扑排序 + 贪心选择，前置关系不被违反，
    已掌握（≥0.8）的知识点不进入推荐。

    Args:
        user_id: 学生业务 ID；None 表示匿名（全部视为未开始学习）
        target_kp_id: 目标知识点 ID；None 表示全局推荐
        count: 推荐步数

    Returns:
        LearningPathData：target（全局模式为 None）+ steps（每步含 reason）

    Raises:
        TargetNotFoundError: 目标知识点不存在
        KnowledgeGraphCycleError: 图谱前置关系存在环

    Note:
        SQL Server 掌握概率查询失败时返回 ``meta.degraded=true``，明确说明
        本次结果未使用个性化掌握度；不得把数据源故障伪装成正常未开始状态。
        Neo4j 异常向上抛，由 router 映射。
    """
    topology = await asyncio.to_thread(_db_load_topology)

    # 目标知识点必须存在
    if target_kp_id is not None and target_kp_id not in topology:
        raise TargetNotFoundError(target_kp_id)

    # 前置映射（后继 → 前置列表）
    prereqs_map: Dict[str, List[str]] = {kp_id: [] for kp_id in topology}
    for kp_id, attrs in topology.items():
        for successor in attrs["successors"]:
            if successor in topology:  # 防御：忽略指向不存在节点的脏边
                prereqs_map[successor].append(kp_id)

    # 对完整图谱做拓扑校验，而不是只校验未掌握候选子图。
    # 否则环路恰好经过已掌握节点时会被过滤掉，产生不可信推荐。
    all_edges = [
        (kp_id, successor)
        for kp_id, attrs in topology.items()
        for successor in attrs["successors"]
        if successor in topology
    ]
    full_topo_order = topological_sort(list(topology), all_edges)

    # 掌握概率：区分匿名、确实无快照和 SQL Server 数据源失败。
    mastery_map: Dict[str, float] = {}
    mastery_source = "anonymous" if not user_id else "no_data"
    degraded = False
    degraded_reason: Optional[str] = None
    if user_id:
        try:
            mastery_map = await asyncio.to_thread(
                _db_query_mastery_map, user_id, list(topology.keys())
            )
            mastery_source = "student_snapshot" if mastery_map else "no_data"
        except Exception as e:
            logger.warning(
                "查询学员掌握概率失败（SQL Server），生成非个性化路径: %s", e
            )
            mastery_source = "unavailable"
            degraded = True
            degraded_reason = "掌握数据暂时不可用，以下路径仅依据图谱与学习成本生成"

    # 候选集合：目标模式只取能到达目标的知识点；已掌握（≥0.8）不推荐
    dist_map: Optional[Dict[str, int]] = None
    if target_kp_id is not None:
        dist_map = compute_distances_to_target(target_kp_id, prereqs_map)
        reachable = set(dist_map.keys())
    else:
        reachable = set(topology.keys())

    candidates = [
        kp_id
        for kp_id in topology
        if kp_id in reachable
        and (
            mastery_map.get(kp_id) is None
            or mastery_map.get(kp_id) < MASTERED_THRESHOLD
        )
    ]

    # 保持全图拓扑顺序，只过滤候选；这样推荐顺序不会因候选裁剪破坏拓扑约束。
    candidate_set = set(candidates)
    topo_order = [kp_id for kp_id in full_topo_order if kp_id in candidate_set]

    path_config = get_path_algorithm_config()

    # 多指标贪心选择
    target_name = topology[target_kp_id]["name"] if target_kp_id else None
    raw_steps = greedy_select_path(
        candidates=topo_order,
        prereqs_map=prereqs_map,
        mastery_map=mastery_map,
        node_attrs=topology,
        dist_map=dist_map,
        target_id=target_kp_id,
        target_name=target_name,
        count=count,
        config=path_config,
        mastery_source=mastery_source,
    )

    steps = [
        PathStep(
            order=step["order"],
            knowledge_point={"id": step["id"], "name": step["name"]},
            reason=step["reason"],
            difficulty=step["difficulty"],
            estimated_time=step["estimated_time"],
            mastery_probability=step["mastery_probability"],
            status=step["status"],
            locked=step["locked"],
            reason_codes=step["reason_codes"],
            score_components=step["score_components"],
        )
        for step in raw_steps
    ]

    return LearningPathData(
        target=PathTarget(id=target_kp_id, name=target_name)
        if target_kp_id
        else None,
        steps=steps,
        meta={
            "algorithm_version": path_config.algorithm_version,
            "weight_profile": path_config.profile,
            "degraded": degraded,
            "degraded_reason": degraded_reason,
            "mastery_source": mastery_source,
            "weights": path_config.weights,
        },
    )


def _merge_degraded_reasons(reasons: List[Optional[str]]) -> Optional[str]:
    """合并固定的用户可读降级原因，不把内部异常传给客户端。"""
    unique_reasons: List[str] = []
    for reason in reasons:
        if reason and reason not in unique_reasons:
            unique_reasons.append(reason)
    return "；".join(unique_reasons) if unique_reasons else None


async def explain_path(
    user_id: Optional[str],
    target_kp_id: Optional[str],
    count: int = 5,
) -> PathExplainData:
    """生成路径推荐的通俗解释（大模型优先，失败降级为规则解释）

    先按 /path 同规则生成推荐路径，再调用大模型生成通俗解释；
    大模型未配置/超时/失败/输出异常时降级为规则拼装的解释
    （总则第八章：调用失败时返回降级内容，不阻塞业务流程）。

    Args:
        user_id: 学生业务 ID；路由层已保证为有效学生身份
        target_kp_id: 目标知识点 ID；None 表示全局推荐
        count: 解释的路径步数

    Returns:
        PathExplainData：解释文本及准确的降级状态（任何情况下 explanation 均非空）

    Raises:
        TargetNotFoundError: 目标知识点不存在
        KnowledgeGraphCycleError: 图谱前置关系存在环
    """
    data = await recommend_path(user_id, target_kp_id, count)

    fallback = build_rule_based_explanation(data)
    degraded_reasons: List[Optional[str]] = [
        data.meta.degraded_reason if data.meta.degraded else None
    ]
    if not data.steps:
        return PathExplainData(
            explanation=fallback,
            degraded=data.meta.degraded,
            degraded_reason=_merge_degraded_reasons(degraded_reasons),
        )  # 无步骤时无需调用大模型

    user_prompt = build_path_explain_user_prompt(
        target_name=data.target.name if data.target else None,
        steps=[
            {
                "order": step.order,
                "name": step.knowledge_point.name,
                "mastery_probability": step.mastery_probability,
                "difficulty": step.difficulty,
                "estimated_time": step.estimated_time,
                "reason": step.reason,
            }
            for step in data.steps
        ],
    )

    try:
        # llm_service 内部已兜底（未配置/超时/重试耗尽均返回 None），
        # 这里再包一层异常保护作为双保险
        text = await chat_completion(
            messages=[
                {"role": "system", "content": PATH_EXPLAIN_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=600,
        )
    except Exception as e:
        logger.warning("路径解释大模型调用异常，降级为规则解释: %s", e)
        text = None

    # 基本校验：非空且长度合理（总则第八章），否则降级
    if isinstance(text, str) and text.strip() and len(text.strip()) <= MAX_EXPLAIN_LENGTH:
        return PathExplainData(
            explanation=text.strip(),
            degraded=data.meta.degraded,
            degraded_reason=_merge_degraded_reasons(degraded_reasons),
        )
    if isinstance(text, str) and text:
        logger.warning("大模型解释长度异常（%d 字符），降级为规则解释", len(text))
    elif text is not None:
        logger.warning("大模型解释返回类型异常，降级为规则解释")
    degraded_reasons.append("大模型解释不可用，已使用规则解释")
    return PathExplainData(
        explanation=fallback,
        degraded=True,
        degraded_reason=_merge_degraded_reasons(degraded_reasons),
    )
