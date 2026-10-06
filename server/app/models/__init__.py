"""数据模型模块"""

from app.models.response import ApiResponse, PaginatedData
from app.models.status_code import StatusCode
from app.models.knowledge_point import (
    KnowledgePointBrief,
    KnowledgePointCreateRequest,
    KnowledgePointDetail,
    KnowledgePointItem,
    PrerequisitesUpdateRequest,
)
from app.models.question import (
    QuestionBatchImportRequest,
    QuestionBatchImportResult,
    QuestionCreateRequest,
    QuestionDetail,
    QuestionImportError,
    QuestionListItem,
    QuestionListQuery,
    QuestionOption,
)
from app.models.student_knowledge_point import (
    StudentKnowledgePointDetail,
    StudentKnowledgePointItem,
    StudentKnowledgePointList,
    StudentKnowledgePointQuestionItem,
    StudentPrerequisiteItem,
)
from app.models.student_question import (
    StudentQuestionItem,
    StudentQuestionList,
    StudentQuestionQuery,
)
from app.models.answer_submission import (
    AnswerSubmitRequest,
    BatchAnswerResult,
    MasteryChangeItem,
    SubmitAnswerResult,
    SubmitBatchRequest,
    SubmitBatchResult,
    SubmitBatchSummary,
)
from app.models.diagnosis import DiagnosisResult
from app.models.learning_path import (
    LearningPathData,
    PathExplainData,
    PathKnowledgePoint,
    PathStep,
    PathTarget,
)
from app.models.graph import GraphData, GraphEdge, GraphMeta, GraphNode, GraphView

__all__ = [
    "ApiResponse",
    "PaginatedData",
    "StatusCode",
    "KnowledgePointBrief",
    "KnowledgePointCreateRequest",
    "KnowledgePointDetail",
    "KnowledgePointItem",
    "PrerequisitesUpdateRequest",
    "QuestionBatchImportRequest",
    "QuestionBatchImportResult",
    "QuestionCreateRequest",
    "QuestionDetail",
    "QuestionImportError",
    "QuestionListItem",
    "QuestionListQuery",
    "QuestionOption",
    "StudentKnowledgePointDetail",
    "StudentKnowledgePointItem",
    "StudentKnowledgePointList",
    "StudentKnowledgePointQuestionItem",
    "StudentPrerequisiteItem",
    "StudentQuestionItem",
    "StudentQuestionList",
    "StudentQuestionQuery",
    "AnswerSubmitRequest",
    "BatchAnswerResult",
    "MasteryChangeItem",
    "SubmitAnswerResult",
    "SubmitBatchRequest",
    "SubmitBatchResult",
    "SubmitBatchSummary",
    "DiagnosisResult",
    "LearningPathData",
    "PathExplainData",
    "PathKnowledgePoint",
    "PathStep",
    "PathTarget",
    "GraphData",
    "GraphEdge",
    "GraphMeta",
    "GraphNode",
    "GraphView",
]
