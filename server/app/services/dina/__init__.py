"""DINA 认知诊断算法包

纯 Python 实现的 DINA（Deterministic Inputs, Noisy "And" gate）认知诊断，
不依赖任何外部 ML 库（scikit-learn / PyTorch 等）：

- qmatrix.py    Q 矩阵管理（题目 × 知识点，从 SQL Server q_matrix 表加载）
- em.py         题目参数 EM 估计（失误率 s / 猜测率 g，de la Torre 2009）
- inference.py  学生知识掌握向量 α 的贝叶斯后验推断
"""

from app.services.dina.qmatrix import QMatrix, QMatrixError
from app.services.dina.em import EmResult, estimate_item_parameters
from app.services.dina.inference import infer_mastery_posterior

__all__ = [
    "QMatrix",
    "QMatrixError",
    "EmResult",
    "estimate_item_parameters",
    "infer_mastery_posterior",
]
