"""
知识点管理相关 Pydantic 数据模型

请求/响应字段严格对照 docs/API契约文档.md「1.1 知识点管理」。
所有字段通过 Pydantic 校验，不手写校验逻辑。
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class KnowledgePointCreateRequest(BaseModel):
    """新增/编辑知识点请求体（POST 与 PUT 共用）

    Attributes:
        name: 知识点名称
        description: 知识点描述
        chapter_id: 所属章节 ID
        difficulty: 难度系数，0.0 ~ 1.0
        estimated_time: 预估学习时长（分钟）
    """

    name: str = Field(..., min_length=1, max_length=100, description="知识点名称")
    description: str = Field(default="", max_length=2000, description="知识点描述")
    chapter_id: str = Field(..., min_length=1, max_length=32, description="所属章节 ID")
    difficulty: float = Field(..., ge=0.0, le=1.0, description="难度系数 0.0~1.0")
    estimated_time: int = Field(..., ge=1, le=600, description="预估学习时长（分钟）")
    prerequisite_ids: Optional[List[str]] = Field(
        default=None,
        max_length=500,
        description="可选；与知识点字段在同一 Neo4j 事务中全量替换前置关系",
    )


class PrerequisitesUpdateRequest(BaseModel):
    """全量替换前置依赖请求体

    Attributes:
        prerequisite_ids: 前置知识点 ID 列表，全量替换（传什么就是什么），
            空列表表示清空所有前置
    """

    prerequisite_ids: List[str] = Field(
        default_factory=list,
        max_length=500,
        description="前置知识点 ID 列表（全量替换）",
    )


class KnowledgePointBrief(BaseModel):
    """前置/后继知识点简要信息

    Attributes:
        id: 知识点 ID
        name: 知识点名称
    """

    id: str
    name: str


class KnowledgePointDetail(BaseModel):
    """知识点详情（含前置/后继知识点）

    Attributes:
        id: 知识点 ID
        name: 知识点名称
        description: 知识点描述
        chapter_id: 所属章节 ID
        chapter_name: 所属章节名称（图谱中无章节节点时为 None）
        difficulty: 难度系数
        estimated_time: 预估学习时长（分钟）
        prerequisites: 前置知识点列表
        dependents: 后继知识点列表（以当前知识点为前置的）
    """

    id: str
    name: str
    description: str
    chapter_id: str
    chapter_name: Optional[str] = None
    difficulty: float
    estimated_time: int
    prerequisites: List[KnowledgePointBrief] = []
    dependents: List[KnowledgePointBrief] = []


class KnowledgePointItem(BaseModel):
    """知识点列表项

    Attributes:
        id: 知识点 ID
        name: 知识点名称
        description: 知识点描述
        chapter_id: 所属章节 ID
        chapter_name: 所属章节名称（图谱中无章节节点时为 None）
        difficulty: 难度系数
        estimated_time: 预估学习时长（分钟）
        prerequisite_count: 前置知识点数量（Neo4j 拓扑统计）
        question_count: 关联题目数量（SQL Server q_matrix 统计）
        created_at: 创建时间（ISO 8601，历史导入数据可能无此属性）
    """

    id: str
    name: str
    description: str
    chapter_id: str
    chapter_name: Optional[str] = None
    difficulty: float
    estimated_time: int
    prerequisite_count: int = 0
    question_count: int = 0
    created_at: Optional[str] = None
