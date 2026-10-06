"""
DINA 认知诊断 — 题目参数 EM 估计（de la Torre, 2009）

EM 算法估计每道题目的两个参数：
- 失误率 s_j：学生已掌握题目考察的全部知识点，仍答错的概率；
- 猜测率 g_j：学生未掌握任一考察知识点，仍答对的概率。

设学生 i 的潜在掌握模式 α（K 维 0/1 向量，K = 知识点总数），题目 j
的理想作答 η_ij = ∏_k α_ik^{q_jk}（掌握 q_j 全部知识点才「会做」），
作答概率（DINA 核心方程）：

    P(X_ij=1 | α) = (1-s_j)^{η_ij} · g_j^{1-η_ij}

EM 迭代（每个学生只对其实际作答过的题目求和，天然支持缺失数据）：
- E 步：P(α|X_i) ∝ P(α) · ∏_j P(X_ij|α)（类先验 P(α) 按独立属性构造，
  边际取全体学生掌握概率均值）；
- M 步：ŝ_j = Σ_{i,α:η=1} w·(1-X) / Σ_{i,α:η=1} w；
        ĝ_j = Σ_{i,α:η=0} w·X / Σ_{i,α:η=0} w（w 为后验权）。

E 步按学生自适应选择后验算法（AI开发总则第七条「纯 Python 实现」）：
1. 精确全枚举：在学生「作答涉及的知识点」子空间上枚举 2^m 个掌握模式
   （m = 该生作答题目涉及的知识点个数）。作答未涉及的知识点无证据、
   后验 = 先验，故子空间枚举与全空间精确推断数学等价；2^m ≤ max_classes
   （默认 1024，即 m ≤ 10）时使用；
2. 置信传播（loopy BP）：m 超过上限时，在知识点变量 × 题目因子的
   因子图上运行阻尼 sum-product（common.belief_propagation）。因子图
   为树时收敛于精确后验；含环时为标准 loopy BP 近似，仅在精确枚举
   不可行时兜底使用。

收敛准则严格按 AI开发总则第七条：
- 参数最大变化 < convergence_threshold（config: 0.001）即收敛；
- 最大迭代 max_iterations（config: 500）；
- s/g 初始值来自 config，并钳制在 [0.1, 0.3]。

纯 Python 实现，不依赖任何外部 ML 库。
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from app.services.dina.common import (
    belief_propagation,
    clamp_prob,
    exact_subspace_posterior,
    subspace_log_prior,
    subspace_question_masks,
)
from app.services.dina.qmatrix import QMatrix

logger = logging.getLogger(__name__)

# 总则第七条：s/g 初始值范围 [0.1, 0.3]
S_G_INIT_MIN = 0.1
S_G_INIT_MAX = 0.3

# 分母保护：期望作答人数低于该值时保持当前参数（题目几乎无人作答）
MIN_EXPECTED_COUNT = 1e-9

# 默认每学生精确枚举的潜在模式数量上限：2^m ≤ 1024（m ≤ 10）时精确，
# 超过则对该学生改用置信传播近似
DEFAULT_MAX_CLASSES = 1024

# 全样本作答矩阵：每位学生一份 {题目索引: 0/1}，仅含实际作答过的题目
ResponseData = List[Dict[int, int]]


@dataclass
class EmResult:
    """EM 估计结果

    Attributes:
        slip: 每题失误率 s（与 qmatrix.question_ids 同序）
        guess: 每题猜测率 g
        iterations: 实际迭代次数
        converged: 是否按收敛阈值提前停止
        loglikelihood_history: 每次迭代的对数似然；
            任一学生走置信传播近似时无法计算精确似然，为空列表
    """

    slip: List[float]
    guess: List[float]
    iterations: int
    converged: bool
    loglikelihood_history: List[float] = field(default_factory=list)


def clamp_initial_parameters(s_init: float, g_init: float) -> Tuple[float, float]:
    """将 s/g 初始值钳制到总则规定的 [0.1, 0.3]，越界时记录告警

    Args:
        s_init: 配置的失误率初始值
        g_init: 配置的猜测率初始值

    Returns:
        钳制后的 (s_init, g_init)
    """
    if not math.isfinite(s_init) or not math.isfinite(g_init):
        raise ValueError("DINA s/g 初始值必须是有限数字")
    if not 0.0 <= s_init <= 1.0 or not 0.0 <= g_init <= 1.0:
        raise ValueError("DINA s/g 初始值必须位于 [0, 1]")
    clamped_s = min(S_G_INIT_MAX, max(S_G_INIT_MIN, s_init))
    clamped_g = min(S_G_INIT_MAX, max(S_G_INIT_MIN, g_init))
    if clamped_s != s_init or clamped_g != g_init:
        logger.warning(
            "DINA s/g 初始值越界（总则要求 [0.1, 0.3]），已钳制: "
            "s %.4f→%.4f, g %.4f→%.4f",
            s_init,
            clamped_s,
            g_init,
            clamped_g,
        )
    return clamped_s, clamped_g


def estimate_item_parameters(
    responses: ResponseData,
    qmatrix: QMatrix,
    prior_marginals: List[float],
    s_init: float = 0.2,
    g_init: float = 0.2,
    max_iterations: int = 500,
    convergence_threshold: float = 0.001,
    max_classes: int = DEFAULT_MAX_CLASSES,
) -> EmResult:
    """用 EM 算法估计题目失误率 s 与猜测率 g（de la Torre, 2009）

    E 步按学生自适应：该生作答涉及的知识点数 m 满足 2^m ≤ max_classes
    时做精确全枚举，否则置信传播近似（见模块 docstring）。

    Args:
        responses: 每位学生的作答（题目索引 → 0/1）
        qmatrix: Q 矩阵（行=题目，列=知识点）
        prior_marginals: 各知识点的先验掌握边际概率 P(α_k=1)
            （类先验按独立属性构造）
        s_init: 初始失误率（钳制到 [0.1, 0.3]；对应 config DINA_S_INITIAL）
        g_init: 初始猜测率（对应 config DINA_G_INITIAL）
        max_iterations: 最大迭代次数（对应 config DINA_EM_MAX_ITERATIONS）
        convergence_threshold: 收敛阈值（对应 config
            DINA_EM_CONVERGENCE_THRESHOLD）
        max_classes: 每学生精确枚举的潜在模式数量上限

    Returns:
        EmResult: 估计出的 s/g、迭代次数、收敛状态与似然轨迹
    """
    if max_iterations < 0:
        raise ValueError("DINA EM 最大迭代次数不能为负数")
    if not math.isfinite(convergence_threshold) or convergence_threshold < 0:
        raise ValueError("DINA EM 收敛阈值不能为负数")
    if len(prior_marginals) != qmatrix.K:
        raise ValueError("DINA 先验维度必须等于 Q 矩阵知识点数量")
    s_init, g_init = clamp_initial_parameters(s_init, g_init)
    slip = [s_init] * qmatrix.J
    guess = [g_init] * qmatrix.J

    # 无任何有效作答时无需估计，直接返回初始参数
    if not responses or not any(responses):
        return EmResult(slip=slip, guess=guess, iterations=0, converged=True)

    return _em(
        responses,
        qmatrix,
        prior_marginals,
        slip,
        guess,
        max_iterations,
        convergence_threshold,
        max_classes,
    )


def _m_step(
    qmatrix: QMatrix,
    slip: List[float],
    guess: List[float],
    r1: List[float],
    i1: List[float],
    r0: List[float],
    i0: List[float],
) -> Tuple[List[float], List[float], float]:
    """M 步：按后验加权统计更新 s/g

    Args:
        qmatrix: Q 矩阵
        slip / guess: 当前参数
        r1 / i1: 各题 η=1 的期望人数 / 期望错答数
        r0 / i0: 各题 η=0 的期望人数 / 期望猜对数

    Returns:
        (新 slip, 新 guess, 最大参数变化量)
    """
    new_slip = list(slip)
    new_guess = list(guess)
    for j in range(qmatrix.J):
        # 期望人数极少的题目保持当前参数（数据不足以更新）
        if r1[j] > MIN_EXPECTED_COUNT:
            new_slip[j] = clamp_prob(i1[j] / r1[j])
        if r0[j] > MIN_EXPECTED_COUNT:
            new_guess[j] = clamp_prob(i0[j] / r0[j])
    max_delta = 0.0
    for j in range(qmatrix.J):
        max_delta = max(
            max_delta,
            abs(new_slip[j] - slip[j]),
            abs(new_guess[j] - guess[j]),
        )
    return new_slip, new_guess, max_delta


def _em(
    responses: ResponseData,
    qmatrix: QMatrix,
    prior_marginals: List[float],
    slip: List[float],
    guess: List[float],
    max_iterations: int,
    convergence_threshold: float,
    max_classes: int,
) -> EmResult:
    """EM 主循环：E 步按学生自适应（精确全枚举 / 置信传播），M 步统一聚合

    Args:
        responses: 每位学生的作答
        qmatrix: Q 矩阵
        prior_marginals: 各知识点先验边际概率
        slip / guess: 初始参数
        max_iterations / convergence_threshold / max_classes: 同公共接口

    Returns:
        EmResult: 估计结果
    """
    j = qmatrix.J
    priors = [clamp_prob(p) for p in prior_marginals]
    question_attributes: List[Set[int]] = [
        set(qmatrix.attribute_indices(qid)) for qid in qmatrix.question_ids
    ]

    # 是否全部学生都能走精确枚举（决定能否记录似然轨迹）
    all_exact = all(
        1 << len({a for cj in resp for a in question_attributes[cj]})
        <= max_classes
        for resp in responses
        if resp
    )

    history: List[float] = []
    for _iteration in range(max_iterations):
        r1 = [0.0] * j
        i1 = [0.0] * j
        r0 = [0.0] * j
        i0 = [0.0] * j
        total_loglik = 0.0

        for resp in responses:
            if not resp:
                # 无作答记录的学生：后验 = 先验，期望按先验边际乘积贡献
                for cj in range(j):
                    e_eta = 1.0
                    for attr in question_attributes[cj]:
                        e_eta *= priors[attr]
                    r1[cj] += e_eta
                    r0[cj] += 1.0 - e_eta
                continue

            active = sorted(
                {attr for cj in resp for attr in question_attributes[cj]}
            )
            attr_bit = {attr: bit for bit, attr in enumerate(active)}
            sub_masks = subspace_question_masks(
                resp, question_attributes, attr_bit
            )

            if (1 << len(active)) <= max_classes:
                # 精确全枚举：活跃子空间上 2^m 个掌握模式
                log_prior_sub = subspace_log_prior(active, priors)
                _, eta_expectations, loglik = exact_subspace_posterior(
                    resp,
                    sub_masks,
                    slip,
                    guess,
                    log_prior_sub,
                    len(active),
                )
                total_loglik += loglik
                for cj, x in resp.items():
                    e_eta = eta_expectations[cj]
                    r1[cj] += e_eta
                    r0[cj] += 1.0 - e_eta
                    i1[cj] += (1.0 - x) * e_eta
                    i0[cj] += x * (1.0 - e_eta)
            else:
                # 置信传播：因子图 sum-product（树图精确，含环时阻尼近似）
                _, eta_expectations = belief_propagation(
                    resp, question_attributes, slip, guess, priors, active
                )
                for cj, x in resp.items():
                    e_eta = eta_expectations[cj]
                    r1[cj] += e_eta
                    r0[cj] += 1.0 - e_eta
                    i1[cj] += (1.0 - x) * e_eta
                    i0[cj] += x * (1.0 - e_eta)

        if all_exact:
            history.append(total_loglik)

        new_slip, new_guess, max_delta = _m_step(
            qmatrix, slip, guess, r1, i1, r0, i0
        )
        slip, guess = new_slip, new_guess
        if max_delta < convergence_threshold:
            return EmResult(
                slip=slip,
                guess=guess,
                iterations=_iteration + 1,
                converged=True,
                loglikelihood_history=history,
            )
    return EmResult(
        slip=slip,
        guess=guess,
        iterations=max_iterations,
        converged=False,
        loglikelihood_history=history,
    )
