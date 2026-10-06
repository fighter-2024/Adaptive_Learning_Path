"""学员正式取题接口的数据模型。

该模型与管理端 ``QuestionDetail`` 分离，故意不包含 answer、explanation
或任何等价的正确答案字段。
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.question import KnowledgePointId, QuestionOption

StudentQuestionType = Literal["single_choice", "multi_choice", "true_false"]


class StudentQuestionQuery(BaseModel):
    """GET /api/student/questions 查询参数。"""

    knowledge_point_id: KnowledgePointId = Field(..., description="知识点 ID")
    count: int = Field(default=10, ge=1, le=50, description="取题数量")
    exclude_done: bool = Field(default=False, description="是否排除已作答题目")
    type: Optional[StudentQuestionType] = Field(default=None, description="题型筛选")


class StudentQuestionItem(BaseModel):
    """学生可见的题目对象；不含答案和解析。"""

    id: str
    content: str
    type: StudentQuestionType
    difficulty: float
    options: List[QuestionOption] = Field(default_factory=list)


class StudentQuestionList(BaseModel):
    """正式取题响应数据。"""

    list: List[StudentQuestionItem] = Field(default_factory=list)  # noqa: A003
    total: int = 0
