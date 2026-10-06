"""
DINA 认知诊断 — 共享数值工具（纯 Python，无外部 ML 依赖）

提供 EM 估计与贝叶斯后验推断共用的数值函数：
- 概率钳制与对数运算（避免 0/1 退化值导致 log(0) 发散）
- 数值稳定的 logsumexp
- 活跃知识点子空间的先验、位掩码与精确后验枚举
- 置信传播（loopy BP）近似边际后验

参考：de la Torre, J. (2009). DINA Model and Parameter Estimation:
A Didactic. Journal of Educational and Behavioral Statistics, 34(1).
"""

import math
from typing import Dict, List, Set, Tuple

# 概率数值边界：避免 0/1 退化导致对数发散（对估计结果影响可忽略）
MIN_PROB = 1e-6
MAX_PROB = 1.0 - MIN_PROB


def clamp_prob(value: float, low: float = MIN_PROB, high: float = MAX_PROB) -> float:
    """将概率钳制到 [low, high]，避免 0/1 退化值

    Args:
        value: 待钳制的概率
        low: 下界（默认 1e-6）
        high: 上界（默认 1-1e-6）

    Returns:
        钳制后的概率
    """
    return min(high, max(low, value))


def logsumexp(values: List[float]) -> float:
    """数值稳定的 log(Σ exp(x))

    Args:
        values: 对数域数值列表

    Returns:
        log(Σ exp(x_i))；空列表返回 -inf
    """
    if not values:
        return -math.inf
    maximum = max(values)
    if maximum == -math.inf:
        return -math.inf
    return maximum + math.log(sum(math.exp(value - maximum) for value in values))


def subspace_log_prior(active: List[int], priors: List[float]) -> List[float]:
    """计算活跃知识点子空间上各掌握模式的对数先验

    子空间维度 m = len(active)，模式位掩码第 bit 位对应 active[bit]。
    先验按独立属性边际乘积（P(α) = ∏ p_k^{α_k}(1-p_k)^{1-α_k}）。

    Args:
        active: 活跃知识点索引列表（子空间的属性）
        priors: 全维度先验边际 P(α_k=1)

    Returns:
        长度 2^m 的对数先验列表（按下标 = 位掩码排列）
    """
    m = len(active)
    log_prior = [0.0] * (1 << m)
    for mask in range(1 << m):
        value = 0.0
        for bit, attr in enumerate(active):
            p = clamp_prob(priors[attr])
            value += math.log(p) if (mask >> bit) & 1 else math.log(1.0 - p)
        log_prior[mask] = value
    return log_prior


def subspace_question_masks(
    resp: Dict[int, int],
    question_attributes: List[Set[int]],
    attr_bit: Dict[int, int],
) -> Dict[int, int]:
    """把学生作答的题目映射为子空间位掩码（仅含活跃属性位）

    Args:
        resp: 学生作答 {题目索引: 0/1}
        question_attributes: 每题考察的知识点索引集合
        attr_bit: 活跃属性索引 → 子空间位序 的映射

    Returns:
        {题目索引: 子空间位掩码}
    """
    sub_masks: Dict[int, int] = {}
    for cj in resp:
        mask = 0
        for attr in question_attributes[cj]:
            bit = attr_bit.get(attr)
            if bit is not None:
                mask |= 1 << bit
        sub_masks[cj] = mask
    return sub_masks


def exact_subspace_posterior(
    resp: Dict[int, int],
    sub_masks: Dict[int, int],
    slip: List[float],
    guess: List[float],
    log_prior: List[float],
    n_attributes: int,
) -> Tuple[List[float], Dict[int, float], float]:
    """在 n_attributes 维子空间上全枚举 2^n 个掌握模式求精确后验

    后验 P(α|X) ∝ P(α) · ∏_j P(X_j|α)，对数域计算，logsumexp 归一化。
    未作答涉及的属性不参与枚举（其边际后验 = 先验，数学上等价）。

    Args:
        resp: 学生作答 {题目索引: 0/1}
        sub_masks: 题目在子空间上的属性位掩码
        slip / guess: 题目参数（与题目索引对齐）
        log_prior: 子空间各模式的对数先验（长度 2^n_attributes）
        n_attributes: 子空间维度 m

    Returns:
        (marginals, eta_expectations, loglik)：
        - marginals: 按位序排列的各属性边际后验 P(α_k=1|X)
        - eta_expectations: {题目索引: P(η=1|X)}（理想作答的期望，
          η=1 即掌握该题全部考察知识点）
        - loglik: 该学生的观测对数似然 log P(X)
    """
    n_classes = 1 << n_attributes
    log_post = list(log_prior)
    for mask in range(n_classes):
        for cj, x in resp.items():
            qm = sub_masks[cj]
            eta = 1 if (mask & qm) == qm else 0
            s, g = slip[cj], guess[cj]
            if eta:
                p = (1.0 - s) if x else s
            else:
                p = g if x else (1.0 - g)
            log_post[mask] += math.log(clamp_prob(p))

    total = logsumexp(log_post)
    posterior = [math.exp(v - total) for v in log_post]

    marginals = [
        sum(
            posterior[mask]
            for mask in range(n_classes)
            if (mask >> bit) & 1
        )
        for bit in range(n_attributes)
    ]
    eta_expectations = {
        cj: sum(
            posterior[mask]
            for mask in range(n_classes)
            if (mask & qm) == qm
        )
        for cj, qm in sub_masks.items()
    }
    return marginals, eta_expectations, total


def belief_propagation(
    responses: Dict[int, int],
    question_attributes: List[Set[int]],
    slip: List[float],
    guess: List[float],
    priors: List[float],
    active: List[int],
    max_sweeps: int = 100,
    tol: float = 1e-8,
    damping: float = 0.5,
) -> Tuple[Dict[int, float], Dict[int, float]]:
    """置信传播（loopy BP，消息阻尼）近似学生的知识点边际后验

    在「活跃知识点变量 × 作答题目因子」构成的因子图上运行 sum-product：
    - 变量→因子消息 m_{k→j}(α_k)：知识点 k 对题目 j 的边际信念
        （先验 × 除 j 外所有因子传入消息的乘积，归一化）；
    - 因子→变量消息 μ_{j→k}(α_k) = Σ_{α_{q_j∖k}} P(X_j|α_{q_j}) ·
        ∏_{l∈q_j∖k} m_{l→j}(α_l)（枚举题目其余知识点的全部取值）。

    因子图无环（树）时收敛于精确后验；含环时以阻尼消息迭代到不动点
    （loopy BP，标准近似，偏差远小于平均场近似）。

    Args:
        responses: 学生作答 {题目索引: 0/1}，仅含实际作答的题目
        question_attributes: 每题考察的知识点索引集合（与 slip/guess 对齐）
        slip: 题目失误率
        guess: 题目猜测率
        priors: 全维度先验边际 P(α_k=1)
        active: 活跃知识点索引（变量集合）
        max_sweeps: 最大消息迭代轮数
        tol: 消息最大变化收敛阈值
        damping: 消息阻尼系数（0=完全保留旧消息，1=不阻尼）

    Returns:
        (marginals, eta_expectations)：
        - marginals: {知识点索引: P(α_k=1|X)}
        - eta_expectations: {题目索引: P(η_j=1|X)}（因子信念中
          「全部考察知识点均掌握」配置的概率）
    """
    # 作答因子按题目索引展开，因子只取学生实际作答的题目
    factors = [(cj, x) for cj, x in responses.items()]

    # 先验钳制与便捷查找
    clamped = {k: clamp_prob(priors[k]) for k in active}

    # 变量→因子消息：{知识点: {题目: (P(α=0), P(α=1))}}，初始化为先验
    var_msg = {
        k: {
            cj: (1.0 - clamped[k], clamped[k])
            for cj, _ in factors
            if k in question_attributes[cj]
        }
        for k in active
    }

    # 因子→变量消息：{题目: {知识点: (μ(0), μ(1))}}，初始化为 (1, 1) 占位
    factor_msg = {
        cj: {
            k: (1.0, 1.0)
            for k in active
            if k in question_attributes[cj]
        }
        for cj, _ in factors
    }

    for _ in range(max_sweeps):
        max_delta = 0.0
        # ---- 因子 → 变量 ----
        for cj, x in factors:
            attrs = sorted(a for a in active if a in question_attributes[cj])
            s, g = slip[cj], guess[cj]
            # 题目作答似然：P(X=x | 该题属性配置)，全 1 才算「会做」
            likelihood: Dict[Tuple[int, ...], float] = {}
            n = len(attrs)
            for bits in range(1 << n):
                config = tuple(1 if (bits >> t) & 1 else 0 for t in range(n))
                all_mastered = all(config)
                if all_mastered:
                    p = (1.0 - s) if x else s
                else:
                    p = g if x else (1.0 - g)
                likelihood[config] = clamp_prob(p)
            # 对每个变量 k 汇总其余变量的消息（枚举 k 取值 × 其余变量配置）
            for k in attrs:
                others = [a for a in attrs if a != k]
                n_other = len(others)
                mu0 = 0.0
                mu1 = 0.0
                for v in (0, 1):
                    total = 0.0
                    for bits in range(1 << n_other):
                        config = [0] * n
                        for t, a in enumerate(others):
                            config[attrs.index(a)] = (bits >> t) & 1
                        config[attrs.index(k)] = v
                        w = likelihood[tuple(config)]
                        for t, a in enumerate(others):
                            m0, m1 = var_msg[a][cj]
                            w *= m1 if (bits >> t) & 1 else m0
                        total += w
                    if v == 0:
                        mu0 = total
                    else:
                        mu1 = total
                z = mu0 + mu1
                if z <= 0:
                    mu0, mu1 = 0.5, 0.5
                else:
                    mu0, mu1 = mu0 / z, mu1 / z
                # 消息阻尼
                old0, old1 = factor_msg[cj][k]
                new0 = damping * mu0 + (1.0 - damping) * old0
                new1 = damping * mu1 + (1.0 - damping) * old1
                max_delta = max(max_delta, abs(new0 - old0), abs(new1 - old1))
                factor_msg[cj][k] = (new0, new1)
        # ---- 变量 → 因子 ----
        for k in active:
            for cj in [cj for cj, _ in factors if k in question_attributes[cj]]:
                p0, p1 = (1.0 - clamped[k]), clamped[k]
                for other_cj, _ in factors:
                    if other_cj == cj or k not in question_attributes[other_cj]:
                        continue
                    mu0, mu1 = factor_msg[other_cj][k]
                    p0 *= mu0
                    p1 *= mu1
                z = p0 + p1
                var_msg[k][cj] = (p0 / z, p1 / z) if z > 0 else (0.5, 0.5)
        if max_delta < tol:
            break

    # ---- 变量边际信念 ----
    marginals: Dict[int, float] = {}
    for k in active:
        p0, p1 = (1.0 - clamped[k]), clamped[k]
        for cj, _ in factors:
            if k in question_attributes[cj]:
                mu0, mu1 = factor_msg[cj][k]
                p0 *= mu0
                p1 *= mu1
        z = p0 + p1
        marginals[k] = p1 / z if z > 0 else clamped[k]

    # ---- 因子信念：η_j = 1（全 1 配置）的后验概率 ----
    eta_expectations: Dict[int, float] = {}
    for cj, x in factors:
        attrs = sorted(a for a in active if a in question_attributes[cj])
        s, g = slip[cj], guess[cj]
        n = len(attrs)
        total = 0.0
        prob_all = 0.0
        for bits in range(1 << n):
            config = tuple(1 if (bits >> t) & 1 else 0 for t in range(n))
            all_mastered = all(config)
            if all_mastered:
                p = (1.0 - s) if x else s
            else:
                p = g if x else (1.0 - g)
            weight = clamp_prob(p)
            for t, a in enumerate(attrs):
                m0, m1 = var_msg[a][cj]
                weight *= m1 if config[t] else m0
            total += weight
            if all_mastered:
                prob_all = weight
        eta_expectations[cj] = prob_all / total if total > 0 else 0.0

    return marginals, eta_expectations
