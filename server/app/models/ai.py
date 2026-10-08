"""M9 请求与响应模型。"""
from typing import Annotated, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

MessageText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
StudentId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]


class HistoryMessage(BaseModel):
    """客户端不能注入 system 发言。"""
    model_config = ConfigDict(extra='forbid')
    role: Literal['user', 'assistant']
    content: MessageText


class ChatRequest(BaseModel):
    """通用答疑请求。"""
    model_config = ConfigDict(extra='forbid')
    message: MessageText
    history: list[HistoryMessage] = Field(default_factory=list, max_length=20)
    # 兼容旧客户端的显式身份参数；服务端只信任 JWT 身份并在路由边界校验。
    student_id: Optional[StudentId] = None


class KnowledgeChatRequest(ChatRequest):
    """知识点答疑请求。"""
    knowledge_point_id: str = Field(min_length=1, max_length=32)


class StudentIdentityBody(BaseModel):
    """诊断解读 body 的可选身份参数；其他字段保持严格拒绝。"""
    model_config = ConfigDict(extra='forbid')
    student_id: Optional[StudentId] = None


class KnowledgeRef(BaseModel):
    """真实图谱引用。"""
    id: str
    name: str


class Degradation(BaseModel):
    """降级信息。"""
    degraded: bool = False
    degraded_reason: Optional[str] = None


class DiagnosisExplain(Degradation):
    """诊断解读。"""
    explanation: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    suggestion: str


class ChatReply(Degradation):
    """答疑及关联卡片。"""
    reply: str
    related_knowledge_points: list[KnowledgeRef] = Field(default_factory=list)


class KnowledgeChatReply(ChatReply):
    """知识点答疑额外返回当前知识点名称。"""
    knowledge_point_name: str


class WeeklyReport(Degradation):
    """真实统计与模型总结。"""
    week_start: str
    week_end: str
    questions_done: int
    correct_rate: float
    study_time_minutes: int
    new_mastered: list[KnowledgeRef] = Field(default_factory=list)
    still_weak: list[KnowledgeRef] = Field(default_factory=list)
    ai_summary: str
    generated_at: str
    cached: bool = False
