"""
学员端答题提交相关 Pydantic 数据模型

请求/响应字段严格对照 docs/改进计划与任务卡/API契约文档-v2.md「3.3 答题」：
- POST /submit-answer  提交单题答案
  请求：question_id / student_answer / time_spent
  响应：correct / correct_answer / explanation / mastery_change
- POST /submit-batch   批量提交
  请求：answers 数组（每项同 submit-answer）

批量响应按契约「每题的判题结果汇总」语义提供：
    data = {results: [每题判题结果...], summary: {汇总统计}}

mastery_change 为知识点 ID → 掌握概率变化 的映射（契约示例：
{"kp_001": {"before": 0.88, "after": 0.92}}）。
"""

from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field, model_validator

AnswerValue = Union[str, List[str]]


class AnswerSubmitRequest(BaseModel):
    """提交单题答案请求体（submit-answer 与 submit-batch 数组项共用）

    Attributes:
        question_id: 题目 ID
        student_answer: 学生提交的答案（单选/判断为字符串，多选优先为
            label 数组，也兼容逗号分隔字符串）
        time_spent: 答题耗时（秒）；可选，数据库列允许 NULL
    """

    question_id: str = Field(..., min_length=1, max_length=32, description="题目 ID")
    student_answer: AnswerValue = Field(
        ..., min_length=1, max_length=100, description="学生提交的答案"
    )
    time_spent: Optional[int] = Field(
        default=None, ge=0, le=86400, description="答题耗时（秒）"
    )

    @model_validator(mode="after")
    def _validate_answer_shape(self) -> "AnswerSubmitRequest":
        """拒绝空数组、空 label 和过长的数组答案，避免静默丢失作答证据。"""
        if isinstance(self.student_answer, list):
            if not self.student_answer or any(
                not isinstance(value, str) or not value.strip()
                for value in self.student_answer
            ):
                raise ValueError("多选答案不能包含空选项")
            if len(",".join(self.student_answer)) > 100:
                raise ValueError("答案长度不能超过 100 个字符")
        elif not self.student_answer.strip():
            raise ValueError("学生答案不能为空")
        return self


class MasteryChangeItem(BaseModel):
    """单个知识点的掌握概率变化（对照契约 mastery_change 元素）

    Attributes:
        before: 本次作答前的掌握概率
        after: 本次作答后（贝叶斯后验更新）的掌握概率
    """

    before: float
    after: float


class SubmitAnswerResult(BaseModel):
    """提交单题答案响应 data（严格对照契约 POST /submit-answer 响应）

    Attributes:
        correct: 是否答对
        correct_answer: 正确答案（判题后返回，不泄题）
        explanation: 题目解析
        mastery_change: 题目关联知识点的掌握概率变化
            {knowledge_point_id: {before, after}}
    """

    correct: bool
    correct_answer: AnswerValue
    explanation: str = ""
    mastery_change: Dict[str, MasteryChangeItem] = {}


class SubmitBatchRequest(BaseModel):
    """批量提交请求体（对照契约 POST /submit-batch 请求体）

    Attributes:
        answers: 答案数组，每项结构同 POST /submit-answer
    """

    answers: List[AnswerSubmitRequest] = Field(
        ..., min_length=1, max_length=200, description="答案数组（每项同 submit-answer）"
    )


class BatchAnswerResult(BaseModel):
    """批量提交中单题的判题结果（契约未定义出参，按「每题的判题结果汇总」设计）

    判题成功时返回 correct/correct_answer/explanation/mastery_change；
    判题失败（题目不存在/已下线）时 error 给出原因，其余字段为 null。

    Attributes:
        question_id: 题目 ID（批量场景用于对应到具体题目）
        correct: 是否答对；判题失败时为 None
        correct_answer: 正确答案；判题失败时为 None
        explanation: 题目解析；判题失败时为 None
        mastery_change: 知识点掌握概率变化；判题失败时为空
        error: 判题失败原因（仅失败项非空）
    """

    question_id: str
    correct: Optional[bool] = None
    correct_answer: Optional[AnswerValue] = None
    explanation: Optional[str] = None
    mastery_change: Dict[str, MasteryChangeItem] = {}
    error: Optional[str] = None


class SubmitBatchSummary(BaseModel):
    """批量提交汇总统计

    Attributes:
        total: 提交的答案总数（= answers 数组长度）
        correct_count: 答对题数
        wrong_count: 答错题数
        fail_count: 判题失败题数（题目不存在等）
        correct_rate: 正确率 = correct_count / (total - fail_count)，
            无有效判题时为 0.0
    """

    total: int
    correct_count: int
    wrong_count: int
    fail_count: int
    correct_rate: float


class SubmitBatchResult(BaseModel):
    """批量提交响应 data（每题的判题结果 + 汇总统计）"""

    results: List[BatchAnswerResult] = []
    summary: SubmitBatchSummary
