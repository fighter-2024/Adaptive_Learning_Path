"""管理端仪表盘与学生数据看板的数据模型。

这些模型只描述管理端读取接口的响应结构；数据查询和跨数据库组装由
``admin_dashboard_service`` 负责，避免把 SQL/Neo4j 细节带入 router。
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.learning_path import PathStep


class RecentDiagnosisItem(BaseModel):
    """仪表盘最近诊断摘要。"""

    student_id: str
    student_name: str
    diagnosed_at: str
    average_mastery: Optional[float] = None


class DashboardSummary(BaseModel):
    """管理端仪表盘汇总数据。"""

    student_count: int = Field(..., ge=0)
    question_count: int = Field(..., ge=0)
    knowledge_point_count: int = Field(..., ge=0)
    weekly_active_students: int = Field(..., ge=0)
    recent_diagnoses: List[RecentDiagnosisItem] = Field(default_factory=list)


class StudentListItem(BaseModel):
    """学生列表项。"""

    student_id: str
    username: str
    name: str
    total_questions_done: int = Field(..., ge=0)
    mastered_kp_count: int = Field(..., ge=0)
    total_kp_count: int = Field(..., ge=0)
    average_mastery: Optional[float] = None
    last_active: Optional[str] = None
    created_at: Optional[str] = None


class StudentDiagnosisSummary(BaseModel):
    """学生单次诊断会话摘要。"""

    session_id: Optional[str] = None
    diagnosed_at: str
    question_count: int = Field(..., ge=0)
    average_mastery: Optional[float] = None
    algorithm_version: Optional[str] = None
    parameter_version: Optional[str] = None
    converged: Optional[bool] = None
    iterations: Optional[int] = Field(default=None, ge=0)
    answer_time_from: Optional[str] = None
    answer_time_to: Optional[str] = None
    repeat_strategy: Optional[str] = None


class StudentLearningHistoryItem(BaseModel):
    """学生在单个知识点上的掌握与作答统计。"""

    knowledge_point_id: str
    knowledge_point_name: str
    questions_done: int = Field(..., ge=0)
    correct_count: int = Field(..., ge=0)
    correct_rate: Optional[float] = None
    mastery_probability: Optional[float] = None
    updated_at: Optional[str] = None


class StudentAnswerHistoryItem(BaseModel):
    """学生最近一次答题记录。"""

    record_id: str
    question_id: str
    question_content: Optional[str] = None
    student_answer: str
    is_correct: bool
    time_spent: Optional[int] = None
    created_at: str


class StudentDetailMeta(BaseModel):
    """学生详情中受限列表的可追踪元数据。"""

    answer_history_limit: int = Field(..., ge=0)
    diagnosis_history_limit: int = Field(..., ge=0)
    learning_history_total: int = Field(..., ge=0)
    knowledge_point_source: str


class StudentDetail(BaseModel):
    """学生详情看板。"""

    student_id: str
    username: str
    name: str
    avatar: Optional[str] = None
    created_at: Optional[str] = None
    last_login_at: Optional[str] = None
    alpha_vector: Dict[str, float] = Field(default_factory=dict)
    last_diagnosis: Optional[StudentDiagnosisSummary] = None
    diagnosis_history: List[StudentDiagnosisSummary] = Field(default_factory=list)
    learning_history: List[StudentLearningHistoryItem] = Field(default_factory=list)
    answer_history: List[StudentAnswerHistoryItem] = Field(default_factory=list)
    recommended_path: List[PathStep] = Field(default_factory=list)
    meta: StudentDetailMeta
