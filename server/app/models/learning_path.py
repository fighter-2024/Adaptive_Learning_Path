"""学习路径推荐相关 Pydantic 数据模型。

V2 在保留原有字段的基础上，为每一步增加状态、结构化推荐理由和得分构成，
并在 ``meta`` 中记录本次推荐使用的算法、权重 profile 与降级情况。
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class PathKnowledgePoint(BaseModel):
    """路径步骤中的知识点简要信息（对照契约 steps[].knowledge_point）

    Attributes:
        id: 知识点 ID
        name: 知识点名称
    """

    id: str
    name: str


class PathTarget(BaseModel):
    """路径目标知识点（对照契约 data.target）

    Attributes:
        id: 目标知识点 ID
        name: 目标知识点名称
    """

    id: str
    name: str


class PathStep(BaseModel):
    """V2 推荐学习路径中的一步。"""

    order: int
    knowledge_point: PathKnowledgePoint
    reason: str
    difficulty: float
    estimated_time: int
    mastery_probability: Optional[float] = None
    status: str = "not_started"
    locked: bool = False
    reason_codes: List[str] = Field(default_factory=list)
    score_components: Dict[str, float] = Field(default_factory=dict)


class PathMeta(BaseModel):
    """推荐运行元数据，便于前端和验收追踪算法来源。"""

    algorithm_version: str = "greedy-v1"
    weight_profile: str = "default-v1"
    degraded: bool = False
    degraded_reason: Optional[str] = None
    mastery_source: str = "none"
    weights: Dict[str, float] = Field(default_factory=dict)


class LearningPathData(BaseModel):
    """学习路径响应 data（对照契约 GET /path 响应）

    Attributes:
        target: 目标知识点；全局推荐（未传 target_kp_id）时为 None
        steps: 推荐学习步骤列表，序列满足拓扑序（前置关系不违反）
    """

    target: Optional[PathTarget] = None
    steps: List[PathStep] = Field(default_factory=list)
    meta: PathMeta = Field(default_factory=PathMeta)


class PathExplainData(BaseModel):
    """路径 AI 解释响应 data（对照契约 GET /path/explain 响应）

    Attributes:
        explanation: 面向学生的通俗解释文本；大模型不可用时为
            规则拼装的降级解释，保证接口始终返回可用内容
        degraded: 是否使用了掌握数据或大模型解释的降级路径
        degraded_reason: 面向用户的降级原因；正常成功时为 None
    """

    explanation: str
    degraded: bool = False
    degraded_reason: Optional[str] = None
