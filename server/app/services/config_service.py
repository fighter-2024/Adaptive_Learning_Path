"""运行时系统配置服务。

配置初始值来自 pydantic-settings；管理端更新只影响当前进程，持久化配置仍应
通过部署环境的 ``.env`` 管理，避免把密钥或运行时状态写入仓库。
"""

import math
from dataclasses import dataclass
from typing import Any, Dict

from app.config import settings
from app.config.security import mask_secret
from app.models.system_config import SystemConfigData, SystemConfigUpdate

PATH_ALGORITHM_VERSION = "greedy-v1"

_UPDATABLE_SETTING_FIELDS = {
    "dina_em_max_iterations": "DINA_EM_MAX_ITERATIONS",
    "dina_em_convergence_threshold": "DINA_EM_CONVERGENCE_THRESHOLD",
    "dina_s_initial": "DINA_S_INITIAL",
    "dina_g_initial": "DINA_G_INITIAL",
    "path_weight_mastery": "PATH_WEIGHT_MASTERY",
    "path_weight_target_distance": "PATH_WEIGHT_TARGET_DISTANCE",
    "path_weight_difficulty": "PATH_WEIGHT_DIFFICULTY",
    "path_weight_time_cost": "PATH_WEIGHT_TIME_COST",
    "path_weight_profile": "PATH_WEIGHT_PROFILE",
    "llm_provider": "LLM_PROVIDER",
    "llm_model": "LLM_MODEL",
    "llm_timeout": "LLM_TIMEOUT",
}
_NULLABLE_ONLY_API_KEY = "llm_api_key"


@dataclass(frozen=True)
class PathAlgorithmConfig:
    """一次推荐计算所使用的不可变路径算法参数快照。"""

    mastery: float
    target_distance: float
    difficulty: float
    time_cost: float
    profile: str
    algorithm_version: str = PATH_ALGORITHM_VERSION

    @property
    def weights(self) -> Dict[str, float]:
        """返回契约字段名对应的权重，供解释字段和日志使用。"""
        return {
            "mastery": self.mastery,
            "target_distance": self.target_distance,
            "difficulty": self.difficulty,
            "time_cost": self.time_cost,
        }


def validate_path_weights(weights: Dict[str, float]) -> None:
    """校验路径权重范围和组合，非法配置统一抛出 ValueError。"""
    required = {"mastery", "target_distance", "difficulty", "time_cost"}
    if set(weights) != required:
        raise ValueError("路径权重必须包含掌握度、目标距离、难度和预计时间四项")
    if any(not math.isfinite(value) or value < 0 or value > 1 for value in weights.values()):
        raise ValueError("路径权重必须都在 0 到 1 之间")
    if abs(sum(weights.values()) - 1.0) > 0.0001:
        raise ValueError("路径权重总和必须为 1")


def get_path_algorithm_config() -> PathAlgorithmConfig:
    """读取当前配置并生成一次推荐使用的参数快照。"""
    weights = {
        "mastery": float(settings.PATH_WEIGHT_MASTERY),
        "target_distance": float(settings.PATH_WEIGHT_TARGET_DISTANCE),
        "difficulty": float(settings.PATH_WEIGHT_DIFFICULTY),
        "time_cost": float(settings.PATH_WEIGHT_TIME_COST),
    }
    validate_path_weights(weights)
    return PathAlgorithmConfig(
        mastery=weights["mastery"],
        target_distance=weights["target_distance"],
        difficulty=weights["difficulty"],
        time_cost=weights["time_cost"],
        profile=settings.PATH_WEIGHT_PROFILE,
    )


def get_system_config() -> SystemConfigData:
    """返回管理端可见的配置安全视图。"""
    return _build_system_config(_current_settings_snapshot())


def _current_settings_snapshot() -> Dict[str, Any]:
    """读取可由管理端更新的配置，形成不可变更前的候选基线。"""
    return {
        "DINA_EM_MAX_ITERATIONS": settings.DINA_EM_MAX_ITERATIONS,
        "DINA_EM_CONVERGENCE_THRESHOLD": settings.DINA_EM_CONVERGENCE_THRESHOLD,
        "DINA_S_INITIAL": settings.DINA_S_INITIAL,
        "DINA_G_INITIAL": settings.DINA_G_INITIAL,
        "PATH_WEIGHT_MASTERY": settings.PATH_WEIGHT_MASTERY,
        "PATH_WEIGHT_TARGET_DISTANCE": settings.PATH_WEIGHT_TARGET_DISTANCE,
        "PATH_WEIGHT_DIFFICULTY": settings.PATH_WEIGHT_DIFFICULTY,
        "PATH_WEIGHT_TIME_COST": settings.PATH_WEIGHT_TIME_COST,
        "PATH_WEIGHT_PROFILE": settings.PATH_WEIGHT_PROFILE,
        "LLM_PROVIDER": settings.LLM_PROVIDER,
        "LLM_MODEL": settings.LLM_MODEL,
        "LLM_TIMEOUT": settings.LLM_TIMEOUT,
        "LLM_API_KEY": settings.LLM_API_KEY,
    }


def _validate_finite_number(name: str, value: Any, minimum: float, maximum: float) -> None:
    """校验候选配置中的数值，不让 None/NaN/无穷值进入运行时 settings。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 类型无效")
    numeric_value = float(value)
    if not math.isfinite(numeric_value) or not minimum <= numeric_value <= maximum:
        raise ValueError(f"{name} 必须在 {minimum} 到 {maximum} 之间")


def _validate_candidate_config(candidate: Dict[str, Any]) -> None:
    """在任何写入前校验完整候选配置。"""
    max_iterations = candidate["DINA_EM_MAX_ITERATIONS"]
    if (
        isinstance(max_iterations, bool)
        or not isinstance(max_iterations, int)
        or not 1 <= max_iterations <= 5000
    ):
        raise ValueError("dina_em_max_iterations 必须是 1 到 5000 的整数")

    _validate_finite_number(
        "dina_em_convergence_threshold",
        candidate["DINA_EM_CONVERGENCE_THRESHOLD"],
        0,
        1,
    )
    if candidate["DINA_EM_CONVERGENCE_THRESHOLD"] == 0:
        raise ValueError("dina_em_convergence_threshold 必须大于 0")
    _validate_finite_number("dina_s_initial", candidate["DINA_S_INITIAL"], 0.1, 0.3)
    _validate_finite_number("dina_g_initial", candidate["DINA_G_INITIAL"], 0.1, 0.3)

    validate_path_weights(
        {
            "mastery": float(candidate["PATH_WEIGHT_MASTERY"]),
            "target_distance": float(candidate["PATH_WEIGHT_TARGET_DISTANCE"]),
            "difficulty": float(candidate["PATH_WEIGHT_DIFFICULTY"]),
            "time_cost": float(candidate["PATH_WEIGHT_TIME_COST"]),
        }
    )

    profile = candidate["PATH_WEIGHT_PROFILE"]
    if not isinstance(profile, str) or not profile.strip() or len(profile) > 64:
        raise ValueError("path_weight_profile 不能为空且长度不能超过 64")
    provider = candidate["LLM_PROVIDER"]
    if not isinstance(provider, str) or not provider.strip() or len(provider) > 32:
        raise ValueError("llm_provider 不能为空且长度不能超过 32")
    model = candidate["LLM_MODEL"]
    if not isinstance(model, str) or not model.strip() or len(model) > 100:
        raise ValueError("llm_model 不能为空且长度不能超过 100")
    timeout = candidate["LLM_TIMEOUT"]
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 300:
        raise ValueError("llm_timeout 必须是 1 到 300 的整数")
    if not isinstance(candidate["LLM_API_KEY"], str):
        raise ValueError("llm_api_key 类型无效")


def _build_system_config(candidate: Dict[str, Any]) -> SystemConfigData:
    """从已校验候选快照构造安全响应，确保提交前完成响应模型校验。"""
    _validate_candidate_config(candidate)
    return SystemConfigData(
        dina_em_max_iterations=candidate["DINA_EM_MAX_ITERATIONS"],
        dina_em_convergence_threshold=candidate["DINA_EM_CONVERGENCE_THRESHOLD"],
        dina_s_initial=candidate["DINA_S_INITIAL"],
        dina_g_initial=candidate["DINA_G_INITIAL"],
        path_weight_mastery=candidate["PATH_WEIGHT_MASTERY"],
        path_weight_target_distance=candidate["PATH_WEIGHT_TARGET_DISTANCE"],
        path_weight_difficulty=candidate["PATH_WEIGHT_DIFFICULTY"],
        path_weight_time_cost=candidate["PATH_WEIGHT_TIME_COST"],
        path_weight_profile=candidate["PATH_WEIGHT_PROFILE"],
        llm_provider=candidate["LLM_PROVIDER"],
        llm_model=candidate["LLM_MODEL"],
        llm_timeout=candidate["LLM_TIMEOUT"],
        llm_api_key_configured=bool(candidate["LLM_API_KEY"]),
        llm_api_key_masked=mask_secret(candidate["LLM_API_KEY"]),
    )


def update_system_config(payload: SystemConfigUpdate) -> SystemConfigData:
    """原子校验并应用管理端配置更新，永不返回原始 API Key。

    ``exclude_unset`` 保留了显式 ``null``，因此这里必须在构造候选快照时单独
    拒绝非密钥字段的 ``null``。所有校验和响应模型构造完成后才写入 settings，
    从而保证一个失败请求不会留下半套运行时配置。
    """
    updates = payload.model_dump(exclude_unset=True)
    for field_name, value in updates.items():
        if field_name != _NULLABLE_ONLY_API_KEY and value is None:
            raise ValueError(f"{field_name} 不能为 null；省略字段表示保持原值")

    before = _current_settings_snapshot()
    candidate = dict(before)
    for request_name, setting_name in _UPDATABLE_SETTING_FIELDS.items():
        if request_name in updates:
            candidate[setting_name] = updates[request_name]

    # 密钥的 null、空串和省略均表示不修改；只有非空值才进入候选配置。
    if updates.get(_NULLABLE_ONLY_API_KEY):
        candidate["LLM_API_KEY"] = updates[_NULLABLE_ONLY_API_KEY]

    # 所有可能失败的检查都发生在写入前，包括响应模型校验。
    validated_response = _build_system_config(candidate)

    try:
        for setting_name, value in candidate.items():
            if value != before[setting_name]:
                setattr(settings, setting_name, value)
    except Exception:
        # 正常情况下不会触发；用于保证意外赋值失败也不留下半套配置。
        for setting_name, value in before.items():
            setattr(settings, setting_name, value)
        raise
    return validated_response
