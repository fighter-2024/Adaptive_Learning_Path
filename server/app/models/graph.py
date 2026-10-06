"""
知识图谱统一响应模型。

三种图谱视图和管理端图谱共用这一组模型，避免前端为不同接口维护
不同的节点、边和元数据结构。
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


GraphView = Literal["tree", "network", "personalized"]
GraphNodeType = Literal["course", "chapter", "knowledge_point"]
GraphNodeStatus = Literal["mastered", "learning", "weak", "not_started"]
GraphRelation = Literal["belongs_to", "prerequisite", "recommended_next", "related"]


class GraphNode(BaseModel):
    """图谱节点，学生状态字段在管理端始终为 ``None``。"""

    id: str
    label: str
    node_type: GraphNodeType
    chapter_id: Optional[str] = None
    difficulty: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    estimated_time: Optional[int] = Field(default=None, ge=0)
    mastery_probability: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    status: Optional[GraphNodeStatus] = None
    locked: Optional[bool] = None
    recommend_order: Optional[int] = None
    reason: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class GraphEdge(BaseModel):
    """图谱有向边。``recommended`` 仅表示当前推荐路径高亮。"""

    id: str
    source: str
    target: str
    relation: GraphRelation
    directed: bool = True
    recommended: bool = False


class GraphMeta(BaseModel):
    """图谱查询范围和截断信息。"""

    view: GraphView
    focus_id: Optional[str] = None
    total_nodes: int = Field(..., ge=0)
    returned_nodes: int = Field(..., ge=0)
    truncated: bool = False
    layout_hint: str = "dagre"
    algorithm_version: Optional[str] = None
    weight_profile: Optional[str] = None


class GraphData(BaseModel):
    """统一 GraphData 响应体。"""

    nodes: List[GraphNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)
    meta: GraphMeta
