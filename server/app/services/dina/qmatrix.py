"""
DINA 认知诊断 — Q 矩阵管理

Q 矩阵（题目 × 知识点）是 DINA 认知诊断模型的输入。按 AI开发总则
第六条规定，Q 矩阵存储在 SQL Server 的 q_matrix 表
（docs/数据库设计.md「1.4」：每条记录表示「这道题考察了这个知识点」）。

本模块提供纯内存数据结构 QMatrix 及校验逻辑（纯 Python，无外部依赖）；
数据库加载由 diagnosis_service 完成。

约束（AI开发总则第七条）：
- Q 矩阵中每个题目至少对应一个知识点（validate 显式校验）；
- 学生 α 向量维度 = 知识点总数（即 QMatrix.K，矩阵列数）。
"""

from typing import Dict, List, Tuple

# 题目-知识点关联行：(question_id, knowledge_point_id)
QMatrixRow = Tuple[str, str]


class QMatrixError(ValueError):
    """Q 矩阵数据异常（矩阵为空等）"""


class QMatrix:
    """题目 × 知识点 的 0/1 关联矩阵

    Attributes:
        question_ids: 题目 ID 列表（行，去重并保持首次出现顺序）
        attribute_ids: 知识点 ID 列表（列，去重并保持首次出现顺序）

    Note:
        知识点 ID 对应 Neo4j KnowledgePoint.id（跨库关联，见数据库设计）。
    """

    def __init__(self, rows: List[QMatrixRow]) -> None:
        """根据 (question_id, knowledge_point_id) 关联行构建矩阵

        Args:
            rows: 题目-知识点关联行列表，可含重复行（去重处理）

        Raises:
            QMatrixError: 关联行为空
        """
        if not rows:
            raise QMatrixError("Q 矩阵为空：q_matrix 表无有效关联数据")
        self.question_ids: List[str] = list(dict.fromkeys(q for q, _ in rows))
        self.attribute_ids: List[str] = list(dict.fromkeys(k for _, k in rows))
        self._question_index: Dict[str, int] = {
            q: i for i, q in enumerate(self.question_ids)
        }
        self._attribute_index: Dict[str, int] = {
            k: i for i, k in enumerate(self.attribute_ids)
        }
        # 0/1 矩阵：行=题目，列=知识点
        self._matrix: List[List[int]] = [[0] * self.K for _ in range(self.J)]
        for question_id, kp_id in rows:
            self._matrix[self._question_index[question_id]][
                self._attribute_index[kp_id]
            ] = 1

    @property
    def J(self) -> int:
        """题目数量（矩阵行数）"""
        return len(self.question_ids)

    @property
    def K(self) -> int:
        """知识点数量（矩阵列数，即学生 α 向量的维度）"""
        return len(self.attribute_ids)

    def has_question(self, question_id: str) -> bool:
        """判断题目是否在 Q 矩阵中

        Args:
            question_id: 题目 ID

        Returns:
            True 表示该题目存在知识点关联
        """
        return question_id in self._question_index

    def question_index(self, question_id: str) -> int:
        """题目对应的行索引

        Raises:
            KeyError: 题目不在 Q 矩阵中
        """
        return self._question_index[question_id]

    def attribute_index(self, kp_id: str) -> int:
        """知识点对应的列索引

        Raises:
            KeyError: 知识点不在 Q 矩阵中
        """
        return self._attribute_index[kp_id]

    def q_vector(self, question_id: str) -> List[int]:
        """题目在 Q 矩阵中的行向量（K 维 0/1）

        Args:
            question_id: 题目 ID

        Returns:
            长度为 K 的 0/1 列表，1 表示该题考察对应知识点
        """
        row = self.question_index(question_id)
        return list(self._matrix[row])

    def question_mask(self, question_id: str) -> int:
        """题目考察知识点的位掩码（第 k 位为 1 表示考察第 k 个知识点）

        供潜在掌握模式枚举使用（Python 整数任意精度，支持任意 K）。

        Args:
            question_id: 题目 ID

        Returns:
            位掩码整数
        """
        row = self.question_index(question_id)
        mask = 0
        for k in range(self.K):
            if self._matrix[row][k]:
                mask |= 1 << k
        return mask

    def attribute_indices(self, question_id: str) -> List[int]:
        """题目考察的知识点列索引列表（升序）

        Args:
            question_id: 题目 ID

        Returns:
            知识点列索引列表
        """
        row = self.question_index(question_id)
        return [k for k in range(self.K) if self._matrix[row][k]]

    def attribute_ids_of(self, question_id: str) -> List[str]:
        """题目考察的知识点 ID 列表（升序）

        Args:
            question_id: 题目 ID

        Returns:
            知识点 ID 列表
        """
        return [
            self.attribute_ids[k] for k in self.attribute_indices(question_id)
        ]

    def active_attribute_indices(self, question_ids: List[str]) -> List[int]:
        """给定题目集合涉及的知识点列索引并集（升序）

        Args:
            question_ids: 题目 ID 列表

        Returns:
            这些题目考察的全部知识点列索引（升序去重）
        """
        active = set()
        for question_id in question_ids:
            active.update(self.attribute_indices(question_id))
        return sorted(active)

    def validate(self) -> None:
        """按 AI开发总则第七条校验 Q 矩阵合法性

        每个题目必须至少对应一个知识点（由构造保证，此处显式校验，
        防止未来改动破坏不变量）。

        Raises:
            QMatrixError: 存在无任何知识点关联的题目
        """
        for j in range(self.J):
            if not any(self._matrix[j]):
                raise QMatrixError(
                    f"题目 {self.question_ids[j]} 在 Q 矩阵中无任何知识点关联"
                )
