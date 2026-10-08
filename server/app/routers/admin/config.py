"""管理端系统配置路由。"""

from fastapi import APIRouter

from app.models import ApiResponse, StatusCode
from app.models.system_config import SystemConfigData, SystemConfigUpdate
from app.services.config_service import get_system_config, update_system_config

router = APIRouter(prefix="/config")


@router.get("", response_model=ApiResponse[SystemConfigData])
async def admin_get_config() -> ApiResponse[SystemConfigData]:
    """读取系统配置安全视图。"""
    return ApiResponse.success(data=get_system_config(), message="获取成功")


@router.put("", response_model=ApiResponse[SystemConfigData])
async def admin_update_config(body: SystemConfigUpdate) -> ApiResponse[SystemConfigData]:
    """更新允许修改的系统配置，不回显原始 API Key。"""
    try:
        data = update_system_config(body)
    except ValueError as exc:
        return ApiResponse.error(code=StatusCode.BAD_REQUEST, message=str(exc))
    return ApiResponse.success(data=data, message="更新成功")
