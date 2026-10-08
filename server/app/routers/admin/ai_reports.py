"""管理员分页查看学习周报。"""
from datetime import date
from fastapi import APIRouter, Query
from app.models import ApiResponse
from app.routers.ai_common import respond as _respond
from app.services.weekly_report_service import list_weekly_reports

router = APIRouter(prefix='/ai-reports')


@router.get('/weekly', response_model=ApiResponse[dict])
async def weekly_reports(page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=20),
                         student_id: str | None = Query(None, max_length=32),
                         week_start: date | None = Query(None)) -> ApiResponse:
    """列表包含完整报告，供管理端抽屉查看。"""
    return await _respond(list_weekly_reports(page, page_size, student_id, week_start))
