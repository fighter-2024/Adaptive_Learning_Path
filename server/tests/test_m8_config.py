"""M8 路径配置与安全回显测试。"""

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.config import settings
from app.main import app
from app.models.system_config import SystemConfigUpdate
from app.routers.dependencies import require_admin
from app.services.config_service import (
    get_path_algorithm_config,
    get_system_config,
    update_system_config,
    validate_path_weights,
)


_NON_NULLABLE_FIELDS = (
    "dina_em_max_iterations",
    "dina_em_convergence_threshold",
    "dina_s_initial",
    "dina_g_initial",
    "path_weight_mastery",
    "path_weight_target_distance",
    "path_weight_difficulty",
    "path_weight_time_cost",
    "path_weight_profile",
    "llm_provider",
    "llm_model",
    "llm_timeout",
)


def _config_snapshot():
    """只比较管理端可见的完整安全配置快照。"""
    return get_system_config().model_dump()


@pytest.fixture
def admin_config_client():
    """隔离配置路由鉴权，测试不依赖真实账号或数据库。"""
    app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(require_admin, None)


def test_invalid_weight_combination_is_rejected():
    """权重范围或总和不合法时不能生成算法配置。"""
    with pytest.raises(ValueError):
        validate_path_weights({"mastery": 0.4, "target_distance": 0.4, "difficulty": 0.4, "time_cost": 0.1})
    with pytest.raises(ValueError):
        Settings(PATH_WEIGHT_MASTERY=1.1)


def test_runtime_update_changes_algorithm_snapshot_and_masks_key(monkeypatch):
    """管理端更新影响后续推荐，并且 API Key 只以掩码返回。"""
    for name, value in {
        "PATH_WEIGHT_MASTERY": 0.4,
        "PATH_WEIGHT_TARGET_DISTANCE": 0.3,
        "PATH_WEIGHT_DIFFICULTY": 0.2,
        "PATH_WEIGHT_TIME_COST": 0.1,
        "PATH_WEIGHT_PROFILE": "default-v1",
        "LLM_API_KEY": "",
    }.items():
        monkeypatch.setattr(settings, name, value)

    data = update_system_config(SystemConfigUpdate(
        path_weight_mastery=0.7,
        path_weight_target_distance=0.1,
        path_weight_difficulty=0.1,
        path_weight_time_cost=0.1,
        path_weight_profile="mastery-first-v1",
        llm_api_key="secret-api-key-value",
    ))
    assert get_path_algorithm_config().profile == "mastery-first-v1"
    assert data.llm_api_key_configured is True
    assert data.llm_api_key_masked != "secret-api-key-value"
    assert data.llm_api_key_masked.endswith("alue")
    assert get_system_config().path_weight_mastery == 0.7


@pytest.mark.parametrize("field_name", _NON_NULLABLE_FIELDS)
def test_explicit_null_rejected_without_mutating_snapshot(
    field_name, admin_config_client
):
    """所有非密钥可更新字段显式 null 都统一拒绝，且失败前后 GET 完全一致。"""
    before = admin_config_client.get("/api/admin/config")
    assert before.status_code == 200
    before_data = before.json()["data"]

    response = admin_config_client.put(
        "/api/admin/config",
        json={field_name: None},
    )
    assert response.status_code == 200
    assert response.json()["code"] == 40000
    assert field_name in response.json()["message"]

    after = admin_config_client.get("/api/admin/config")
    assert after.status_code == 200
    assert after.json()["code"] == 0
    assert after.json()["data"] == before_data


def test_api_key_null_and_empty_string_keep_existing_secret(admin_config_client, monkeypatch):
    """API Key 的 null、空串和省略均保持原值，响应只返回掩码。"""
    secret = "m8-r1-secret-value"
    monkeypatch.setattr(settings, "LLM_API_KEY", secret)
    before = admin_config_client.get("/api/admin/config").json()["data"]

    for value in (None, ""):
        response = admin_config_client.put(
            "/api/admin/config",
            json={"llm_api_key": value},
        )
        assert response.status_code == 200
        assert response.json()["code"] == 0
        data = response.json()["data"]
        assert data["llm_api_key_masked"] == before["llm_api_key_masked"]
        assert secret not in response.text
        assert settings.LLM_API_KEY == secret


def test_invalid_profile_is_rejected_before_any_write(admin_config_client):
    """空 profile 在候选配置阶段被拒绝，后续 GET 仍可用且快照不变。"""
    before = admin_config_client.get("/api/admin/config").json()["data"]
    response = admin_config_client.put(
        "/api/admin/config",
        json={"path_weight_profile": "   "},
    )
    assert response.status_code == 200
    assert response.json()["code"] == 40000
    after = admin_config_client.get("/api/admin/config")
    assert after.status_code == 200
    assert after.json()["data"] == before
    assert get_path_algorithm_config().profile == before["path_weight_profile"]


def test_invalid_weights_are_rejected_atomically(admin_config_client):
    """非法权重组合不污染任何权重，后续路径算法快照仍可生成。"""
    before = admin_config_client.get("/api/admin/config").json()["data"]
    response = admin_config_client.put(
        "/api/admin/config",
        json={
            "path_weight_mastery": 0.9,
            "path_weight_target_distance": 0.2,
        },
    )
    assert response.status_code == 200
    assert response.json()["code"] == 40000
    assert admin_config_client.get("/api/admin/config").json()["data"] == before
    algorithm = get_path_algorithm_config()
    assert algorithm.weights == {
        "mastery": before["path_weight_mastery"],
        "target_distance": before["path_weight_target_distance"],
        "difficulty": before["path_weight_difficulty"],
        "time_cost": before["path_weight_time_cost"],
    }


def test_mixed_valid_and_null_update_is_atomic(admin_config_client):
    """同一请求中的合法 profile 不得在另一个字段 null 失败时提前生效。"""
    before = admin_config_client.get("/api/admin/config").json()["data"]
    response = admin_config_client.put(
        "/api/admin/config",
        json={
            "dina_em_max_iterations": None,
            "path_weight_profile": "m8-r1-must-not-apply",
        },
    )
    assert response.status_code == 200
    assert response.json()["code"] == 40000
    after = admin_config_client.get("/api/admin/config")
    assert after.status_code == 200
    assert after.json()["data"] == before
    assert get_path_algorithm_config().profile == before["path_weight_profile"]
    assert after.json()["data"]["dina_em_max_iterations"] == before["dina_em_max_iterations"]
