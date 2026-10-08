"""M9-R3 真实周报缓存版本与空白事实校验复验。

运行：python scripts/verify_m9_r3.py
只写入脱敏 HTTP/SQL 证据；临时身份在成功或异常后按 user_id 精确清理。
"""
import asyncio
import hashlib
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
from app.services.llm_service import CompletionResult

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / 'docs/Delivery/2026-10-07-M9-R3-http-evidence.json'
logging.getLogger().setLevel(logging.WARNING)
CREATED_IDS: list[str] = []


def call(client: TestClient, method: str, path: str, token: str | None = None,
         body: dict | None = None, params: dict | list[tuple[str, str]] | None = None) -> dict:
    """调用真实应用，不把 Authorization 写入证据。"""
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    kwargs = {'headers': headers, 'params': params or {}}
    if method == 'post':
        kwargs['json'] = body or {}
    response = client.post(path, **kwargs) if method == 'post' else client.get(path, **kwargs)
    payload = response.json()
    return {'http': response.status_code, 'code': payload.get('code'), 'message': payload.get('message', '')}


async def register_temp(label: str, role: str, suffix: str) -> tuple[dict, str]:
    username = f'm9r3_{label}_{suffix}'
    password = secrets.token_urlsafe(24)
    info = await register(username, password, f'M9-R3-{label}', role)
    CREATED_IDS.append(info.user_id)
    return {'user_id': info.user_id, 'username': username}, create_jwt_token(
        info.user_id, username, role
    ).token


def cleanup(user_ids: list[str]) -> dict:
    """只删除本批次 user_id 及其关联记录。"""
    conn = get_connection()
    placeholders = ','.join('?' for _ in user_ids)
    counts: dict[str, int] = {}
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


def clear_weekly_cache(user_id: str) -> None:
    """为每个受控模型输出删除唯一用户的摘要，保留真实作答源数据。"""
    conn = get_connection()
    try:
        conn.cursor().execute('DELETE FROM weekly_reports WHERE user_id=?', (user_id,))
        conn.commit()
    finally:
        conn.close()


async def main() -> None:
    suffix = uuid.uuid4().hex[:8]
    created: list[dict] = []
    student_a, token_a = await register_temp('student_a', 'student', suffix)
    student_b, token_b = await register_temp('student_b', 'student', suffix)
    admin, admin_token = await register_temp('admin', 'admin', suffix)
    created.extend([student_a, student_b, admin])
    client = TestClient(app)
    foreign = student_b['user_id']
    evidence = {
        'source': 'real FastAPI TestClient + SQL Server + Neo4j + configured provider',
        'student_a_id': student_a['user_id'], 'student_b_id': student_b['user_id'],
        'week_start': weekly.resolve_week(None).isoformat(),
        'repeated_query': {}, 'auth_priority': {}, 'same_student': {},
        'duration': {}, 'cache': {}, 'r1_bad_cache_under_r3': {},
        'controlled_summary_validation': {}, 'cleanup': None,
    }

    # 所有重复 query 值都进入路由，任一他人值均不得被最后一个本人值覆盖。
    repeated_routes = [
        ('diagnosis', 'post', '/api/student/diagnosis/explain', {}),
        ('chat', 'post', '/api/student/chat', {'message': '问题'}),
        ('knowledge_chat', 'post', '/api/student/chat/knowledge-point',
         {'message': '问题', 'knowledge_point_id': 'kp_001'}),
        ('weekly', 'get', '/api/student/weekly-report', None),
    ]
    for route_name, method, path, body in repeated_routes:
        for order_name, values in (
            ('foreign_then_self', [foreign, student_a['user_id']]),
            ('self_then_foreign', [student_a['user_id'], foreign]),
            ('foreign_then_self_then_self', [foreign, student_a['user_id'], student_a['user_id']]),
        ):
            params = [('student_id', value) for value in values]
            result = call(client, method, path, token_a, body, params)
            evidence['repeated_query'][f'{route_name}_{order_name}'] = {
                'student_id_values': values, **result
            }
            assert (result['http'], result['code']) == (403, 40101)

    # 保留 R1 的鉴权优先级回归。
    expired = jwt.encode({'user_id': student_a['user_id'], 'username': student_a['username'],
                          'role': 'student', 'iat': datetime.now(timezone.utc) - timedelta(hours=2),
                          'exp': datetime.now(timezone.utc) - timedelta(hours=1)},
                         settings.SECRET_KEY, algorithm='HS256')
    auth_tokens = {'anonymous': None, 'invalid': 'not-a-jwt', 'expired': expired, 'wrong_role': admin_token}
    for route_name, method, path, body in repeated_routes:
        evidence['auth_priority'][route_name] = {}
        for auth_name, token in auth_tokens.items():
            result = call(client, method, path, token, body)
            evidence['auth_priority'][route_name][auth_name] = result
            expected = (401, 40100) if auth_name in {'anonymous', 'invalid', 'expired'} else (403, 40101)
            assert (result['http'], result['code']) == expected

    for route_name, method, path, body in repeated_routes:
        params = {'student_id': student_a['user_id']}
        result = call(client, method, path, token_a, body, params)
        evidence['same_student'][route_name] = result
        assert (result['http'], result['code']) == (200, 0)

    # 正式答题 API 写入真实 20 秒作答源数据。
    conn = get_connection()
    try:
        row = conn.cursor().execute(
            'SELECT TOP 1 question_id, answer FROM questions WHERE is_active=1 ORDER BY question_id'
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    submission = call(client, 'post', '/api/student/submit-answer', token_a,
                      {'question_id': row[0], 'student_answer': row[1], 'time_spent': 20})
    assert (submission['http'], submission['code']) == (200, 0)
    source = await asyncio.to_thread(weekly._db_sources, student_a['user_id'], weekly.resolve_week(None))
    evidence['duration']['source_sql_seconds'] = source['time_seconds']
    first = client.get('/api/student/weekly-report', headers={'Authorization': f'Bearer {token_a}'}).json()
    assert first['code'] == 0
    report = first['data']
    evidence['duration'].update({k: report[k] for k in ('study_time_minutes', 'ai_summary', 'degraded')})
    assert report['study_time_minutes'] == 0 and report['degraded'] is False
    assert any(marker in report['ai_summary'] for marker in ('20秒', '20 秒', '不足1分钟', '不足 1 分钟'))
    assert not weekly._contains_missing_duration_claim(report['ai_summary'])

    second = client.get('/api/student/weekly-report', headers={'Authorization': f'Bearer {token_a}'}).json()['data']
    evidence['cache'] = {'first_cached': report['cached'], 'second_cached': second['cached'],
                        'generated_at_unchanged': report['generated_at'] == second['generated_at']}
    assert report['cached'] is False and second['cached'] is True

    # R1 旧摘要样本：故意省略 validator_version，验证规则升级会跳过旧缓存。
    week = weekly.resolve_week(None)
    old_stats = dict(report)
    for key in ('ai_summary', 'generated_at', 'cached', 'degraded', 'degraded_reason'):
        old_stats.pop(key, None)
    old_fingerprint = {
        'source': source, 'stats': old_stats, 'prompt': weekly.WEEKLY_SYSTEM_PROMPT,
        'config': [settings.LLM_PROVIDER, settings.LLM_MODEL, settings.LLM_API_BASE,
                   hashlib.sha256(settings.LLM_API_KEY.encode()).hexdigest(), settings.LLM_TIMEOUT],
    }
    old_digest = hashlib.sha256(json.dumps(
        old_fingerprint, sort_keys=True, ensure_ascii=False
    ).encode()).hexdigest()
    from app.models.ai import WeeklyReport
    legacy = WeeklyReport(**{**report, 'ai_summary': '本周暂无有效作答时长记录；请在下周练习时每题预留20秒。',
                             'cached': False, 'degraded': False, 'degraded_reason': None})
    await asyncio.to_thread(weekly._db_save_cache, student_a['user_id'], week, old_digest, legacy)
    upgraded = client.get('/api/student/weekly-report', headers={'Authorization': f'Bearer {token_a}'}).json()['data']
    upgraded_cached = client.get('/api/student/weekly-report', headers={'Authorization': f'Bearer {token_a}'}).json()['data']
    evidence['r1_bad_cache_under_r3'] = {
        'seed_digest_prefix': old_digest[:12], 'seed_omitted_validator_version': True,
        'first_cached': upgraded['cached'], 'first_summary': upgraded['ai_summary'],
        'second_cached': upgraded_cached['cached'],
        'old_summary_replaced': upgraded['ai_summary'] != legacy.ai_summary,
    }
    assert upgraded['cached'] is False and upgraded_cached['cached'] is True
    assert upgraded['ai_summary'] != legacy.ai_summary

    # 受控模型反例：保留真实 SQL 源，只替换 validator 输入，验证空白正反例。
    original_complete = weekly.complete
    bad_summaries = {
        'spaced_contradiction': '本周没有有效的作答时 长记录。已记录作答时长20秒，不足1分钟。',
        'spaced_correct': '本周已记录作答时长 20 秒，不足 1 分钟，按整分钟显示为 0 分钟。',
        'newline_correct': '本周已记录作答时长\n20\t秒，不足\n1 分钟，按整分钟显示为 0 分钟。',
    }
    try:
        for name, bad in bad_summaries.items():
            clear_weekly_cache(student_a['user_id'])

            async def fake_complete(messages, validator=None, _bad=bad, **kwargs):
                try:
                    content = validator(json.dumps({'ai_summary': _bad}, ensure_ascii=False)) if validator else None
                    return CompletionResult(content=content, reason='')
                except Exception as error:
                    return CompletionResult(content=None, reason=str(error))

            weekly.complete = fake_complete
            controlled = await weekly.get_weekly_report(student_a['user_id'], weekly.resolve_week(None))
            evidence['controlled_summary_validation'][name] = {
                'input': bad, 'degraded': controlled.degraded,
                'summary': controlled.ai_summary, 'reason': controlled.degraded_reason,
            }
            if name == 'spaced_contradiction':
                assert controlled.degraded and _duration_fallback_is_present(controlled.ai_summary)
            else:
                assert not controlled.degraded and controlled.ai_summary == bad
    finally:
        weekly.complete = original_complete

    evidence['cleanup'] = cleanup([item['user_id'] for item in created])
    assert evidence['cleanup']['remaining_users'] == 0
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'cache_version': 'PASS', 'whitespace_validation': 'PASS',
                      'repeated_query': 'PASS', 'duration_validation': 'PASS',
                      'auth_priority': 'PASS', 'cache': 'PASS', 'cleanup': evidence['cleanup'],
                      'evidence': str(EVIDENCE)}, ensure_ascii=False))


def _duration_fallback_is_present(summary: str) -> bool:
    return '已记录作答时长20秒' in summary and '不足1分钟' in summary


if __name__ == '__main__':
    try:
        asyncio.run(main())
    finally:
        if CREATED_IDS:
            cleanup(CREATED_IDS)
