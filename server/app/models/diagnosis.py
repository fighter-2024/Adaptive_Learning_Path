"""
学员端诊断相关 Pydantic 数据模型

严格对照 docs/API契约文档.md「2.3 诊断」POST /api/student/diagnosis 响应：

    data = {
        "alpha_vector": {"kp_001": 0.92, "kp_002": 0.78},
        "diagnosed_at": "2026-03-20T18:30:00"
    }

alpha_vector 维度 = Q 矩阵知识点总数（AI开发总则第七条「学生 α 向量
维度 = 知识点总数」），值为贝叶斯后验 P(α_k=1|X)；无作答证据的
知识点保持先验值（上一轮 α，无记录取 0.5）。
"""

from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field


class DiagnosisTrace(BaseModel):
    """DINA 诊断可追踪信息。

    这些字段与 V2 接口契约一致，用于复现本次诊断使用的算法、参数和
    答题范围；不包含 SQL、内部异常或敏感配置。
    """

    algorithm_version: str = Field(..., description="DINA 算法版本")
    parameter_version: str = Field(..., description="参数配置版本")
    answer_count: int = Field(..., ge=0, description="聚合后参与诊断的答题数")
    answer_time_from: Optional[str] = Field(
        default=None, description="参与诊断的最早答题时间（ISO 8601）"
    )
    answer_time_to: Optional[str] = Field(
        default=None, description="参与诊断的最晚答题时间（ISO 8601）"
    )
    repeat_strategy: Literal["latest_attempt"] = Field(
        ..., description="重复作答聚合策略"
    )
    converged: bool = Field(..., description="EM 是否在上限前收敛")
    iterations: int = Field(..., ge=0, description="EM 实际迭代次数")


class DiagnosisResult(BaseModel):
    """DINA 诊断响应 data

    Attributes:
        alpha_vector: 知识掌握向量 {知识点ID: 掌握概率 0.0~1.0}
        diagnosed_at: 诊断完成时间（ISO 8601 字符串，如 2026-03-20T18:30:00）
        trace: 本次诊断算法、参数、答题范围和收敛状态；历史兼容读取时可为空
    """

    alpha_vector: Dict[str, float] = Field(
        default_factory=dict, description="知识掌握概率向量（维度=Q矩阵知识点总数）"
    )
    diagnosed_at: str = Field(..., description="诊断完成时间（ISO 8601）")
    trace: Optional[DiagnosisTrace] = Field(
        default=None, description="诊断可追踪信息（V2）"
    )
