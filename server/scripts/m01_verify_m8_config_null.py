"""M01 验收复现：隔离配置 null/原子性，不连接数据库或修改运行中服务。"""
import logging
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.routers.dependencies import require_admin

logging.disable(logging.CRITICAL)
# 隔离鉴权仅用于配置缺陷复现，不能作为权限验收证据。
app.dependency_overrides[require_admin] = lambda: {'role': 'admin'}
client = TestClient(app, raise_server_exceptions=False)
cases = [
    {'dina_em_max_iterations': None},
    {'dina_em_convergence_threshold': None},
    {'dina_s_initial': None},
    {'dina_g_initial': None},
    {'path_weight_mastery': None},
    {'path_weight_target_distance': None},
    {'path_weight_difficulty': None},
    {'path_weight_time_cost': None},
    {'path_weight_profile': None},
    {'llm_provider': None},
    {'llm_model': None},
    {'llm_timeout': None},
    {'llm_api_key': None},
    {'llm_api_key': ''},
    {'path_weight_mastery': 0.9, 'path_weight_target_distance': 0.2},
    {'path_weight_profile': '   '},
    {'dina_em_max_iterations': None, 'path_weight_profile': 'm01-rejected-but-applied'},
]
try:
    for payload in cases:
        before = dict(settings.__dict__)
        try:
            put = client.put('/api/admin/config', json=payload)
            get = client.get('/api/admin/config')
            state_changed = before != settings.__dict__
            result = {
                'payload': payload,
                'put_http': put.status_code,
                'put_code': put.json()['code'],
                'state_changed': state_changed,
                'get_http': get.status_code,
                'get_code': get.json()['code'],
                'profile_after': settings.PATH_WEIGHT_PROFILE,
            }
            print(result)
            assert put.status_code == 200
            assert get.status_code == 200 and get.json()['code'] == 0
            assert not state_changed, '失败或空密钥更新改变了运行时 settings'
            if 'llm_api_key' in payload and payload['llm_api_key'] in (None, ''):
                assert put.json()['code'] == 0
            else:
                assert put.json()['code'] == 40000
        finally:
            settings.__dict__.clear()
            settings.__dict__.update(before)
    print({'restored_get_http': client.get('/api/admin/config').status_code})
finally:
    app.dependency_overrides.pop(require_admin, None)
