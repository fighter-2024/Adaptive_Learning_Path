"""
学员端知识点相关 Pydantic 数据模型

响应字段严格对照 docs/API契约文档.md「2.1 学习」：
- GET /knowledge-points       列表（data 结构为 {list: [...]}，非分页）
- GET /knowledge-points/{id}  详情（前置知识点掌握状态 + 关联题目列表）

掌握状态 status 枚举（契约原文）：
    mastered     mastery_probability ≥ 0.8
    learning     0.4 ≤ mastery_probability < 0.8
    weak         mastery_probability < 0.4
    not_started  无掌握数据（user_kp_mastery 无该学员记录）
"""

from typing import List, Literal, Optional

from pydantic import BaseModel

# 掌握状态枚举（对照契约「2.1 学习」）
MasteryStatus = Literal["mastered", "learning", "weak", "not_started"]


class StudentKnowledgePointItem(BaseModel):
    """学员视角知识点列表项（对照契约 GET /knowledge-points 响应）

    Attributes:
        id: 知识点 ID
        name: 知识点名称
        chapter_name: 所属章节名称（图谱中无章节节点时为 None）
        difficulty: 难度系数 0.0~1.0
        estimated_time: 预估学习时长（分钟）
        mastery_probability: 学员掌握概率；无诊断数据（或未登录）时为 None
        status: 掌握状态枚举，由 mastery_probability 按阈值计算
    """

    id: str
    name: str
    chapter_name: Optional[str] = None
    difficulty: float
    estimated_time: int
    mastery_probability: Optional[float] = None
    status: MasteryStatus


class StudentKnowledgePointList(BaseModel):
    """学员视角知识点列表响应 data（契约结构为 {list: [...]}，不分页）

    与通用分页格式不同：契约「2.1 学习」中该接口无 total/page/page_size，
    这里严格按契约只保留 list 字段。
    """

    list: List[StudentKnowledgePointItem] = []  # noqa: A003


class StudentPrerequisiteItem(BaseModel):
    """前置知识点掌握状态（对照契约详情响应 prerequisites 元素）

    Attributes:
        id: 前置知识点 ID
        name: 前置知识点名称
        mastered: 该学员是否已掌握此前置知识点（掌握概率 ≥ 0.8）
    """

    id: str
    name: str
    mastered: bool


class StudentKnowledgePointQuestionItem(BaseModel):
    """关联题目摘要（对照契约详情响应 questions 元素）

    学员视角不返回答案与解析（避免泄题），仅返回做题所需的摘要字段。

    Attributes:
        id: 题目 ID
        content: 题干
        type: 题型 single_choice / multi_choice / true_false
        difficulty: 难度系数 0.0~1.0
        done: 该学员是否已做过这道题（answer_records 有记录为 True）
    """

    id: str
    content: str
    type: str
    difficulty: float
    done: bool


class StudentKnowledgePointDetail(BaseModel):
    """学员视角知识点详情（对照契约 GET /knowledge-points/{id} 响应）

    Attributes:
        id: 知识点 ID
        name: 知识点名称
        description: 知识点描述
        difficulty: 难度系数
        estimated_time: 预估学习时长（分钟）
        mastery_probability: 学员掌握概率；无诊断数据时为 None
        prerequisites: 前置知识点及该学员的掌握状态
        questions: 关联题目摘要及该学员的完成状态
    """

    id: str
    name: str
    description: str
    difficulty: float
    estimated_time: int
    mastery_probability: Optional[float] = None
    prerequisites: List[StudentPrerequisiteItem] = []
    questions: List[StudentKnowledgePointQuestionItem] = []
