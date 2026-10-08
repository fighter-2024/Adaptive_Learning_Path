"""M9-R1 真实 HTTP/SQL 复验，创建并精确清理 A/B 临时学生和临时管理员。

用法：python scripts/verify_m9_r1.py
结果写入 docs/Delivery/2026-10-07-M9-R1-http-evidence.json；不保存 Token、密码或 API Key。
"""
import asyncio
import json
import logging
import secrets
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import settings
from app.db.sqlserver import get_connection
from app.main import app
from app.services.auth_service import create_jwt_token, register
from app.services import weekly_report_service as weekly

# scripts/ -> server/ -> creation/；交付证据应写入当前工作区 docs。
ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / 'docs/Delivery/2026-10-07-M9-R1-http-evidence.json'
logging.getLogger().setLevel(logging.WARNING)
CREATED_IDS: list[str] = []


def call(client: TestClient, method: str, path: str, token: str | None = None,
         body: dict | None = None, params: dict | None = None) -> dict:
    """调用真实应用，不把 Authorization 写入证据。"""
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    kwargs = {'headers': headers, 'params': params or {}}
    if method == 'post':
        kwargs['json'] = body or {}
    response = client.post(path, **kwargs) if method == 'post' else client.get(path, **kwargs)
    payload = response.json()
    return {'http': response.status_code, 'code': payload.get('code'), 'message': payload.get('message', '')}


async def register_temp(label: str, role: str, suffix: str) -> tuple[dict, str]:
    """注册临时用户并返回最小清理信息与 JWT。"""
    username = f'm9r1_{label}_{suffix}'
    password = secrets.token_urlsafe(24)
    info = await register(username, password, f'M9-R1-{label}', role)
    CREATED_IDS.append(info.user_id)
    token = create_jwt_token(info.user_id, username, role).token
    return {'user_id': info.user_id, 'username': username}, token


def cleanup(user_ids: list[str]) -> dict:
    """按精确 user_id 在事务内清理本批次，绝不清空表。"""
    conn = get_connection()
    counts: dict[str, int] = {}
    placeholders = ','.join('?' for _ in user_ids)
    try:
        cursor = conn.cursor()
        for table in ('weekly_reports', 'diagnosis_sessions', 'user_kp_mastery',
                      'answer_records', 'check_ins', 'user_achievements', 'users'):
            cursor.execute(f'DELETE FROM {table} WHERE user_id IN ({placeholders})', tuple(user_ids))
            counts[table] = cursor.rowcount
        conn.commit()
        remaining = cursor.execute(
            f'SELECT COUNT(*) FROM users WHERE user_id IN ({placeholders})', tuple(user_ids)
        ).fetchone()[0]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {'deleted': counts, 'remaining_users': int(remaining)}


async def main() -> None:
    """运行身份参数、时长事实、缓存和清理证据。"""
    suffix = uuid.uuid4().hex[:8]
    created: list[dict] = []
    student_a, token_a = await register_temp('student_a', 'student', suffix)
    student_b, token_b = await register_temp('student_b', 'student', suffix)
    admin, admin_token = await register_temp('admin', 'admin', suffix)
    created.extend([student_a, student_b, admin])
    client = TestClient(app)
    evidence = {
        'source': 'real FastAPI TestClient + SQL Server + Neo4j + configured provider',
        'student_a_id': student_a['user_id'], 'student_b_id': student_b['user_id'],
        'week_start': weekly.resolve_week(None).isoformat(),
        'foreign_student_id': {}, 'auth_priority': {}, 'same_student': {},
        'duration': {}, 'cache': {}, 'cleanup': None,
    }
    foreign = student_b['user_id']
    routes = [
        ('diagnosis_query', 'post', '/api/student/diagnosis/explain', {}, {'student_id': foreign}),
        ('chat_query', 'post', '/api/student/chat', {'message': '问题'}, {'student_id': foreign}),
        ('knowledge_chat_query', 'post', '/api/student/chat/knowledge-point',
         {'message': '问题', 'knowledge_point_id': 'kp_001'}, {'student_id': foreign}),
        ('weekly_query', 'get', '/api/student/weekly-report', None, {'student_id': foreign}),
        ('diagnosis_body', 'post', '/api/student/diagnosis/explain', {'student_id': foreign}, {}),
        ('chat_body', 'post', '/api/student/chat', {'message': '问题', 'student_id': foreign}, {}),
        ('knowledge_chat_body', 'post', '/api/student/chat/knowledge-point',
         {'message': '问题', 'knowledge_point_id': 'kp_001', 'student_id': foreign}, {}),
        ('conflicting_channels', 'post', '/api/student/chat?student_id=' + student_a['user_id'],
         {'message': '问题', 'student_id': foreign}, {}),
    ]
    for name, method, path, body, params in routes:
        result = call(client, method, path, token_a, body, params)
        evidence['foreign_student_id'][name] = result
        assert result['http'] == 403 and result['code'] == 40101

    # 鉴权优先级：每条新增学生路由至少覆盖四种凭证状态。
    expired = jwt.encode({'user_id': student_a['user_id'], 'username': student_a['username'],
                          'role': 'student', 'iat': datetime.now(timezone.utc) - timedelta(hours=2),
                          'exp': datetime.now(timezone.utc) - timedelta(hours=1)},
                         settings.SECRET_KEY, algorithm='HS256')
    auth_tokens = {'anonymous': None, 'invalid': 'not-a-jwt', 'expired': expired, 'wrong_role': admin_token}
    auth_routes = [
        ('diagnosis', 'post', '/api/student/diagnosis/explain', {}),
        ('chat', 'post', '/api/student/chat', {'message': '问题'}),
        ('knowledge_chat', 'post', '/api/student/chat/knowledge-point',
         {'message': '问题', 'knowledge_point_id': 'kp_001'}),
        ('weekly', 'get', '/api/student/weekly-report', None),
    ]
    for route_name, method, path, body in auth_routes:
        evidence['auth_priority'][route_name] = {}
        for auth_name, token in auth_tokens.items():
            result = call(client, method, path, token, body)
            evidence['auth_priority'][route_name][auth_name] = result
            expected = (401, 40100) if auth_name in {'anonymous', 'invalid', 'expired'} else (403, 40101)
            assert (result['http'], result['code']) == expected

    # 同身份兼容，但业务服务只得到认证 user_id；空数据学生请求不会读取 B。
    for name, method, path, body, params in [
        ('diagnosis', 'post', '/api/student/diagnosis/explain', {'student_id': student_a['user_id']}, {}),
        ('chat', 'post', '/api/student/chat', {'message': '问题', 'student_id': student_a['user_id']}, {}),
        ('knowledge_chat', 'post', '/api/student/chat/knowledge-point',
         {'message': '问题', 'knowledge_point_id': 'kp_001', 'student_id': student_a['user_id']}, {}),
        ('weekly', 'get', '/api/student/weekly-report', None, {'student_id': student_a['user_id']}),
    ]:
        result = call(client, method, path, token_a, body, params)
        evidence['same_student'][name] = result
        assert result['http'] == 200 and result['code'] == 0

    # 正式接口产生一个正值不足一分钟的真实作答记录；取题只读答案不经过学生响应。
    conn = get_connection()
    try:
        row = conn.cursor().execute('SELECT TOP 1 question_id, answer FROM questions '
            'WHERE is_active=1 ORDER BY question_id').fetchone()
    finally:
        conn.close()
    assert row is not None
    submission = call(client, 'post', '/api/student/submit-answer', token_a,
                      {'question_id': row[0], 'student_answer': row[1], 'time_spent': 20})
    assert submission['http'] == 200 and submission['code'] == 0
    source = await asyncio.to_thread(weekly._db_sources, student_a['user_id'], weekly.resolve_week(None))
    evidence['duration']['source_sql_seconds'] = source['time_seconds']
    evidence['duration']['questions_done'] = source['questions_done']
    # 只读取 data 的报告字段，避免把凭证写入证据；这是答题后的首次读取。
    report_first_response = client.get('/api/student/weekly-report', headers={'Authorization': f'Bearer {token_a}'})
    report_first_json = report_first_response.json()
    assert report_first_response.status_code == 200 and report_first_json['code'] == 0
    report_payload = report_first_json['data']
    evidence['duration'].update({k: report_payload[k] for k in ('study_time_minutes', 'ai_summary', 'degraded')})
    assert report_payload['study_time_minutes'] == 0
    assert any(marker in report_payload['ai_summary'] for marker in
               ('20秒', '20 秒', '不足1分钟', '不足 1 分钟', '不足一分钟'))
    assert '没有有效时长' not in report_payload['ai_summary']
    evidence['duration']['boundary_check'] = 'PASS：20 秒有效记录按 0 分钟显示，摘要保留“不足一分钟”事实'

    # 新规则摘要可命中缓存；Prompt/事实约束在 digest 中，旧错误摘要不会直接命中。
    report_cached = client.get('/api/student/weekly-report', headers={'Authorization': f'Bearer {token_a}'}).json()['data']
    evidence['cache'] = {'first_cached': report_payload['cached'], 'second_cached': report_cached['cached'],
                        'generated_at_unchanged': report_payload['generated_at'] == report_cached['generated_at']}
    assert report_payload['cached'] is False and report_cached['cached'] is True
    evidence['cleanup'] = cleanup([item['user_id'] for item in created])
    assert evidence['cleanup']['remaining_users'] == 0
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'foreign_matrix': 'PASS', 'auth_priority': 'PASS', 'duration': 'PASS',
                      'cache': 'PASS', 'cleanup': evidence['cleanup'], 'evidence': str(EVIDENCE)},
                     ensure_ascii=False))


if __name__ == '__main__':
    try:
        asyncio.run(main())
    finally:
        # 即使断言或模型调用失败，也只清理本次脚本登记的精确 user_id。
        if CREATED_IDS:
            cleanup(CREATED_IDS)
