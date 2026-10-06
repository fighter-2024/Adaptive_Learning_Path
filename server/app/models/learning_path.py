"""
学习路径推荐相关 Pydantic 数据模型

响应字段严格对照 docs/API契约文档.md「2.4 学习路径」：
- GET /path          data: {target: {id, name}, steps: [{order,
                     knowledge_point: {id, name}, reason, difficulty,
                     estimated_time, mastery_probability}]}
- GET /path/explain  data: {explanation}
"""

from typing import List, Optional

from pydantic import BaseModel


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
    """推荐学习路径中的一步（对照契约 data.steps 元素）

    Attributes:
        order: 步骤序号，从 1 开始
        knowledge_point: 知识点简要信息 {id, name}
        reason: 推荐理由（中文，面向学生可读）
        difficulty: 难度系数 0.0~1.0
        estimated_time: 预估学习时长（分钟）
        mastery_probability: 学员当前掌握概率；无诊断数据时为 None
    """

    order: int
    knowledge_point: PathKnowledgePoint
    reason: str
    difficulty: float
    estimated_time: int
    mastery_probability: Optional[float] = None


class LearningPathData(BaseModel):
    """学习路径响应 data（对照契约 GET /path 响应）

    Attributes:
        target: 目标知识点；全局推荐（未传 target_kp_id）时为 None
        steps: 推荐学习步骤列表，序列满足拓扑序（前置关系不违反）
    """

    target: Optional[PathTarget] = None
    steps: List[PathStep] = []


class PathExplainData(BaseModel):
    """路径 AI 解释响应 data（对照契约 GET /path/explain 响应）

    Attributes:
        explanation: 面向学生的通俗解释文本；大模型不可用时为
            规则拼装的降级解释，保证接口始终返回可用内容
    """

    explanation: str
