"""
DINA 认知诊断 — 学生知识掌握向量 α 的贝叶斯后验推断

在题目参数（失误率 s / 猜测率 g）已估计的前提下，依据学生作答结果
推断其知识掌握向量 α 的后验概率：

    P(α_k=1 | X) = Σ_{α: α_k=1} P(α|X)
    P(α|X) ∝ P(α) · ∏_j P(X_j|α)

按 AI开发总则第七条：
- 「贝叶斯后验推断使用上一轮 α 作为先验」：先验取该学生上一轮诊断
  结果（user_kp_mastery 快照），无记录的知识点取中性先验 0.5；
- α 向量维度 = 知识点总数（Q 矩阵列数）。

未在作答题目中出现过的知识点没有证据，其后验 = 先验；推断在该学生
「作答涉及知识点」子空间上进行，与全空间精确推断数学等价。

推断方式与 em.py 对应，按 2^m（m 为作答涉及的知识点数）是否超过
max_classes 自适应选择：
- 精确全枚举（common.exact_subspace_posterior，m 较小时）；
- 置信传播 loopy BP（common.belief_propagation，m 较大时；因子图
  为树时精确，含环时为标准阻尼近似，仅在精确枚举不可行时兜底）。

纯 Python 实现，不依赖任何外部 ML 库。
"""

from typing import Dict, List, Set

from app.services.dina.common import (
    belief_propagation,
    clamp_prob,
    exact_subspace_posterior,
    subspace_log_prior,
    subspace_question_masks,
)
from app.services.dina.em import DEFAULT_MAX_CLASSES
from app.services.dina.qmatrix import QMatrix

# 中性先验：该知识点尚无上一轮诊断结果（user_kp_mastery 无记录）时使用
NEUTRAL_PRIOR = 0.5


def infer_mastery_posterior(
    responses: Dict[int, int],
    qmatrix: QMatrix,
    slip: List[float],
    guess: List[float],
    prior_marginals: List[float],
    max_classes: int = DEFAULT_MAX_CLASSES,
) -> List[float]:
    """推断学生知识掌握向量 α 的后验边际概率

    Args:
        responses: 该学生的作答 {题目索引: 0/1}，仅含实际作答的题目
        qmatrix: Q 矩阵（行=题目，列=知识点）
        slip: 题目失误率（与 qmatrix.question_ids 同序，已由 EM 估计）
        guess: 题目猜测率
        prior_marginals: 全维度先验边际 P(α_k=1)（上一轮 α 向量，
            无记录知识点取 0.5）
        max_classes: 精确枚举潜在模式数量上限，超过则置信传播近似

    Returns:
        与 qmatrix.attribute_ids 同序的 P(α_k=1|X) 列表；
        无作答证据的知识点返回先验值
    """
    priors = [clamp_prob(p) for p in prior_marginals]
    result = list(priors)

    # 仅保留 Q 矩阵内且取值合法的作答
    resp = {
        cj: x
        for cj, x in responses.items()
        if 0 <= cj < qmatrix.J and x in (0, 1)
    }
    if not resp:
        return result

    question_attributes: List[Set[int]] = [
        set(qmatrix.attribute_indices(qid)) for qid in qmatrix.question_ids
    ]
    # 作答涉及的知识点：唯一有证据的部分，其余保持先验
    active = sorted({attr for cj in resp for attr in question_attributes[cj]})
    attr_bit = {attr: bit for bit, attr in enumerate(active)}
    sub_masks = subspace_question_masks(resp, question_attributes, attr_bit)

    if (1 << len(active)) <= max_classes:
        log_prior_sub = subspace_log_prior(active, priors)
        updated, _, _ = exact_subspace_posterior(
            resp, sub_masks, slip, guess, log_prior_sub, len(active)
        )
    else:
        marginals, _ = belief_propagation(
            resp, question_attributes, slip, guess, priors, active
        )
        updated = [marginals[attr] for attr in active]
    for attr, value in zip(active, updated):
        result[attr] = value
    return result
