"""M9 学生解释接口，强制学生身份。"""
from datetime import date
from fastapi import APIRouter, Body, Depends, Query
from app.models import ApiResponse
from app.models.auth import UserInfo
from app.models.ai import ChatRequest, KnowledgeChatRequest, ChatReply, KnowledgeChatReply, DiagnosisExplain, WeeklyReport, StudentIdentityBody, StudentId
from app.routers.dependencies import reject_foreign_student_ids, require_student
from app.services.ai_service import answer_chat, explain_diagnosis
from app.services.weekly_report_service import get_weekly_report
from app.routers.ai_common import respond as _respond

router = APIRouter()


@router.post('/diagnosis/explain', response_model=ApiResponse[DiagnosisExplain])
async def diagnosis_explain(
    body: StudentIdentityBody | None = Body(default=None),
    student_id: list[StudentId] | None = Query(default=None),
    user: UserInfo = Depends(require_student),
) -> ApiResponse:
    """解释当前学生最近诊断。"""
    reject_foreign_student_ids(user, *(student_id or []), body.student_id if body else None)
    return await _respond(explain_diagnosis(user.user_id))


@router.post('/chat', response_model=ApiResponse[ChatReply])
async def chat(
    body: ChatRequest,
    student_id: list[StudentId] | None = Query(default=None),
    user: UserInfo = Depends(require_student),
) -> ApiResponse:
    """通用答疑，不接收其他学生 ID。"""
    reject_foreign_student_ids(user, *(student_id or []), body.student_id)
    return await _respond(answer_chat(body))


@router.post('/chat/knowledge-point', response_model=ApiResponse[KnowledgeChatReply])
async def knowledge_chat(
    body: KnowledgeChatRequest,
    student_id: list[StudentId] | None = Query(default=None),
    user: UserInfo = Depends(require_student),
) -> ApiResponse:
    """限定当前知识点资料的答疑。"""
    reject_foreign_student_ids(user, *(student_id or []), body.student_id)
    return await _respond(answer_chat(body, body.knowledge_point_id))


@router.get('/weekly-report', response_model=ApiResponse[WeeklyReport])
async def weekly_report(week_start: date | None = Query(None),
                        student_id: list[StudentId] | None = Query(default=None),
                        user: UserInfo = Depends(require_student)) -> ApiResponse:
    """读取当前学生真实周报。"""
    reject_foreign_student_ids(user, *(student_id or []))
    return await _respond(get_weekly_report(user.user_id, week_start))
