"""
题库管理相关 Pydantic 数据模型

请求/响应字段严格对照 docs/API契约文档.md「1.2 题库管理」。
选项在 API 层为结构化数组，存储层序列化为 JSON 字符串
（SQL Server questions.options 列，NVARCHAR(MAX)，见 docs/数据库设计.md「1.3 questions」）。
所有请求参数通过 Pydantic 校验，不手写校验逻辑（AI开发总则第四条）。
"""

from typing import Annotated, List, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints, model_validator

# 知识点业务 ID：非空字符串，长度不超过 32（对应 Neo4j KnowledgePoint.id）
KnowledgePointId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)
]


class QuestionOption(BaseModel):
    """题目选项

    Attributes:
        label: 选项标识（如 A/B/C/D；判断题默认「对/错」）
        content: 选项内容
    """

    label: str = Field(..., min_length=1, max_length=10, description="选项标识")
    content: str = Field(..., min_length=1, max_length=500, description="选项内容")


class QuestionCreateRequest(BaseModel):
    """新增/编辑题目请求体（POST 与 PUT 共用）

    业务校验全部由 Pydantic 完成：
    - type 仅允许 single_choice / multi_choice / true_false
    - difficulty 0.0 ~ 1.0
    - 选择题选项至少 2 个、label 不重复、答案必须是选项之一
    - 判断题答案仅 true / false；选项缺省时自动补默认「对/错」
    - 多选题答案支持 "A, C" 写法，自动规范化为 "A,C"
    - knowledge_point_ids 至少 1 个且自动去重（DINA 约束：Q矩阵每题至少一个知识点）
    """

    content: str = Field(..., min_length=1, max_length=2000, description="题目题干")
    type: Literal["single_choice", "multi_choice", "true_false"] = Field(..., description="题目类型")
    difficulty: float = Field(..., ge=0.0, le=1.0, description="难度系数 0.0~1.0")
    options: Optional[List[QuestionOption]] = Field(
        default=None, max_length=26, description="选项列表；判断题可省略"
    )
    answer: str = Field(..., min_length=1, max_length=100, description="正确答案")
    explanation: str = Field(default="", max_length=1000, description="题目解析")
    knowledge_point_ids: List[KnowledgePointId] = Field(
        ..., min_length=1, max_length=50, description="关联知识点 ID 列表"
    )

    @model_validator(mode="after")
    def _validate_options_and_answer(self) -> "QuestionCreateRequest":
        """校验选项与答案的一致性，并规范化答案

        Raises:
            ValueError: 校验失败时给出对用户可读的中文提示
        """
        # 判断题：选项可省略（默认「对/错」），答案仅 true / false
        if self.type == "true_false":
            if self.answer not in ("true", "false"):
                raise ValueError("判断题答案只能是 true 或 false")
            if self.options is None:
                self.options = [
                    QuestionOption(label="对", content="正确"),
                    QuestionOption(label="错", content="错误"),
                ]
            return self

        # 选择题：选项必填且至少 2 个
        if self.options is None:
            raise ValueError("选项不能为空")
        if len(self.options) < 2:
            raise ValueError("选项至少需要 2 个")

        labels = [opt.label for opt in self.options]
        if len(labels) != len(set(labels)):
            raise ValueError("选项标识不能重复")

        if self.type == "single_choice":
            # 单选答案必须是某个选项标识
            if self.answer not in labels:
                raise ValueError("答案必须是选项之一")
        else:  # multi_choice
            # 多选答案：逗号分隔的选项标识（允许空格），规范化为 "A,C" 并去重
            parts = [p for p in (part.strip() for part in self.answer.split(",")) if p]
            if not parts:
                raise ValueError("多选题答案不能为空")
            if any(p not in labels for p in parts):
                raise ValueError("答案必须是选项之一")
            if len(parts) != len(set(parts)):
                raise ValueError("多选题答案不能重复")
            # 按选项出现顺序规范化（数据库存逗号分隔，如 "A,C"）
            label_order = {label: index for index, label in enumerate(labels)}
            self.answer = ",".join(sorted(parts, key=label_order.__getitem__))
        return self

    @model_validator(mode="after")
    def _dedupe_knowledge_point_ids(self) -> "QuestionCreateRequest":
        """知识点 ID 去重（保留首次出现顺序）

        q_matrix 有唯一约束 (question_id, knowledge_point_id)，
        入参重复会导致插入冲突，这里提前去重。
        """
        seen: List[str] = []
        for kp_id in self.knowledge_point_ids:
            if kp_id not in seen:
                seen.append(kp_id)
        self.knowledge_point_ids = seen
        return self


class QuestionListQuery(BaseModel):
    """GET /questions 查询参数模型（分页 + 筛选，对照契约 1.2）

    Attributes:
        page: 页码，从 1 开始
        page_size: 每页条数，默认 20，最大 100
        knowledge_point_id: 按关联知识点筛选
        type: 按题型筛选
        difficulty_min: 难度下限（含），按难度区间筛选
        difficulty_max: 难度上限（含），按难度区间筛选
        keyword: 按题目内容模糊搜索

    Note:
        难度筛选为闭区间 [difficulty_min, difficulty_max]，两个参数可
        单独使用；下限大于上限时校验失败。
    """

    page: int = Field(default=1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(default=20, ge=1, le=100, description="每页条数，默认 20，最大 100")
    knowledge_point_id: Optional[str] = Field(default=None, max_length=32, description="按关联知识点筛选")
    type: Optional[Literal["single_choice", "multi_choice", "true_false"]] = Field(
        default=None, description="按题型筛选"
    )
    difficulty_min: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="难度下限（含），按难度区间筛选 0.0~1.0"
    )
    difficulty_max: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="难度上限（含），按难度区间筛选 0.0~1.0"
    )
    keyword: Optional[str] = Field(default=None, max_length=200, description="按题目内容模糊搜索")

    @model_validator(mode="after")
    def _validate_difficulty_range(self) -> "QuestionListQuery":
        """难度区间交叉校验：下限不能大于上限"""
        if (
            self.difficulty_min is not None
            and self.difficulty_max is not None
            and self.difficulty_min > self.difficulty_max
        ):
            raise ValueError("difficulty_min 不能大于 difficulty_max")
        return self


class QuestionListItem(BaseModel):
    """题目列表项（严格对照契约 GET /questions 响应）"""

    id: str
    content: str
    type: str
    difficulty: float
    knowledge_point_ids: List[str] = []
    knowledge_point_names: List[str] = []
    created_at: Optional[str] = None


class QuestionDetail(BaseModel):
    """题目详情（含选项与解析，对照契约 GET /questions/{id} 响应）"""

    id: str
    content: str
    type: str
    difficulty: float
    options: List[QuestionOption] = []
    answer: str
    explanation: str = ""
    knowledge_point_ids: List[str] = []
    created_at: Optional[str] = None


class QuestionBatchImportRequest(BaseModel):
    """批量导入请求体

    questions 为「结构同 POST 单个」的题目对象数组。为支持逐行错误统计
    （契约要求返回 success_count/fail_count/errors），此处只做浅校验，
    每一行的深度校验在 service 层用 QuestionCreateRequest 完成，
    单行失败只记入 errors，不影响其他行导入。
    """

    questions: List[dict] = Field(
        ..., min_length=1, max_length=500, description="题目对象数组"
    )


class QuestionImportError(BaseModel):
    """批量导入单行失败信息（对照契约 errors 数组元素）"""

    row: int = Field(..., ge=1, description="失败行号（从 1 开始）")
    message: str = Field(..., description="失败原因")


class QuestionBatchImportResult(BaseModel):
    """批量导入结果统计（对照契约 POST /questions/batch-import 响应）"""

    success_count: int = 0
    fail_count: int = 0
    errors: List[QuestionImportError] = []
