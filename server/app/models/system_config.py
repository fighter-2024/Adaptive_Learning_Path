"""管理端系统配置接口的数据模型。"""

from typing import Optional

from pydantic import BaseModel, Field


class SystemConfigData(BaseModel):
    """系统配置安全视图，不包含任何原始密钥。"""

    dina_em_max_iterations: int
    dina_em_convergence_threshold: float
    dina_s_initial: float
    dina_g_initial: float
    path_weight_mastery: float
    path_weight_target_distance: float
    path_weight_difficulty: float
    path_weight_time_cost: float
    path_weight_profile: str
    llm_provider: str
    llm_model: str
    llm_timeout: int
    llm_api_key_configured: bool
    llm_api_key_masked: str


class SystemConfigUpdate(BaseModel):
    """管理端可更新配置。

    缺失字段保持当前值；非密钥字段显式 ``null`` 由服务层拒绝并返回 40000，
    以区分“省略”与“误传空值”。密钥的 ``null``、空串或省略均表示不修改。
    """

    dina_em_max_iterations: Optional[int] = Field(default=None, ge=1, le=5000)
    dina_em_convergence_threshold: Optional[float] = Field(default=None, gt=0, le=1)
    dina_s_initial: Optional[float] = Field(default=None, ge=0.1, le=0.3)
    dina_g_initial: Optional[float] = Field(default=None, ge=0.1, le=0.3)
    path_weight_mastery: Optional[float] = Field(default=None, ge=0, le=1)
    path_weight_target_distance: Optional[float] = Field(default=None, ge=0, le=1)
    path_weight_difficulty: Optional[float] = Field(default=None, ge=0, le=1)
    path_weight_time_cost: Optional[float] = Field(default=None, ge=0, le=1)
    path_weight_profile: Optional[str] = Field(default=None, min_length=1, max_length=64)
    llm_provider: Optional[str] = Field(default=None, min_length=1, max_length=32)
    llm_model: Optional[str] = Field(default=None, min_length=1, max_length=100)
    llm_timeout: Optional[int] = Field(default=None, ge=1, le=300)
    llm_api_key: Optional[str] = Field(default=None, max_length=500)
