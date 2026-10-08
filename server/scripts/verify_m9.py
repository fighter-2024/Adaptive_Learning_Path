"""M9 真实库与真实模型证据；临时身份精确清理，不打印凭证。

用法：python scripts/verify_m9.py prepare / cleanup。
临时登录信息只写入被忽略的 .runtime/m9-session.json。
"""
import asyncio
import io
import json
import logging
import secrets
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.db.sqlserver import get_connection, get_local_now
from app.services.auth_service import register, create_jwt_token
from app.services import weekly_report_service as wr

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / 'server/.runtime/m9-session.json'
EVIDENCE = ROOT / 'docs/Delivery/2026-10-06-M9-http-evidence.json'
logging.getLogger().setLevel(logging.WARNING)
logging.getLogger('neo4j').setLevel(logging.WARNING)


def request(client: TestClient, method: str, path: str, token: str, **kwargs) -> dict:
    """只提取响应 data，不输出头部或凭证。"""
    response = getattr(client, method)(path, headers={'Authorization':f'Bearer {token}'}, **kwargs)
    body = response.json()
    if body['code'] != 0:
        raise RuntimeError(f"{path} code={body['code']} message={body['message']}")
    return body['data']


async def prepare() -> None:
    """创建临时学生/管理员，贯通真实答题、模型、缓存与故障。"""
    if SESSION.exists():
        raise RuntimeError('session exists; clean up previous verification first')
    suffix=uuid.uuid4().hex[:8]
    identities={}
    for role in ('student','admin'):
        password=secrets.token_urlsafe(20)
        username=f'm9_{role}_{suffix}'
        info=await register(username,password,f'M9验证{role}',role)
        token=create_jwt_token(info.user_id,username,role).token
        identities[role]={'user_id':info.user_id,'username':username,'password':password,'token':token}
    SESSION.parent.mkdir(exist_ok=True)
    SESSION.write_text(json.dumps(identities), encoding='utf-8')
    conn=get_connection()
    try:
        cursor=conn.cursor()
        rows=cursor.execute('SELECT TOP 3 q.question_id,q.answer FROM questions q '
            'WHERE q.is_active=1 AND EXISTS (SELECT 1 FROM q_matrix m WHERE m.question_id=q.question_id) '
            'ORDER BY q.question_id').fetchall()
        kp=cursor.execute('SELECT TOP 1 knowledge_point_id FROM q_matrix WHERE question_id=? '
            'ORDER BY knowledge_point_id',(rows[0][0],)).fetchone()[0]
    finally: conn.close()
    identities['kp_id']=kp
    SESSION.write_text(json.dumps(identities),encoding='utf-8')
    student=identities['student']['token']; admin=identities['admin']['token']
    week=wr.resolve_week(None); uid=identities['student']['user_id']
    client=TestClient(app)
    evidence={'student_id':uid,'week_start':str(week),'knowledge_point_id':kp,'provider':settings.LLM_PROVIDER,
              'model':settings.LLM_MODEL,'data_fixture':'临时账号通过正式答题、诊断接口生成数据，重复作答真实入库；仅操作临时身份'}
    evidence['submissions']=[]
    # 真实库可能仅有两道题；明确重做也计入尝试，保持四次初始作答夹具。
    for index in range(3):
        row=rows[index % len(rows)]
        result=request(client,'post','/api/student/submit-answer',student,json={
            'question_id':row[0],'student_answer':row[1],'time_spent':61+index})
        evidence['submissions'].append({'question_id':row[0],'correct':result['correct']})
    result=request(client,'post','/api/student/submit-answer',student,json={
        'question_id':rows[0][0],'student_answer':'incorrect','time_spent':65})
    evidence['submissions'].append({'question_id':rows[0][0],'correct':result['correct']})
    evidence['diagnosis']=request(client,'post','/api/student/diagnosis',student)
    evidence['normal_diagnosis']=request(client,'post','/api/student/diagnosis/explain',student)
    print('Real diagnosis explanation completed',flush=True)
    evidence['normal_chat']=request(client,'post','/api/student/chat/knowledge-point',student,
        json={'message':'请解释这个知识点，并给一个学习步骤。','knowledge_point_id':kp,'history':[]})
    evidence['normal_general_chat']=request(client,'post','/api/student/chat',student,
        json={'message':'一元一次方程应该怎样移项？','history':[]})
    evidence['normal_path']=request(client,'get','/api/student/path/explain',student)
    print('Real chat and path explanations completed',flush=True)
    evidence['report_first']=request(client,'get','/api/student/weekly-report',student)
    evidence['report_cached']=request(client,'get','/api/student/weekly-report',student)
    assert evidence['report_cached']['cached'] is True
    assert evidence['report_first']['generated_at']==evidence['report_cached']['generated_at']
    assert evidence['report_first']['questions_done']==4
    assert evidence['report_first']['correct_rate']==.75
    assert evidence['report_first']['study_time_minutes']==4
    # 正式接口产生新记录后，摘要必须立即失效。
    request(client,'post','/api/student/submit-answer',student,json={
        'question_id':rows[0][0],'student_answer':rows[0][1],'time_spent':60})
    evidence['report_invalidated']=request(client,'get','/api/student/weekly-report',student)
    assert not evidence['report_invalidated']['cached'] and evidence['report_invalidated']['questions_done']==5
    evidence['source_sql']=await asyncio.to_thread(wr._db_sources,uid,week)
    evidence['admin_reports']=request(client,'get','/api/admin/ai-reports/weekly',admin,params={'student_id':uid})
    print('Real report cache and data invalidation verified',flush=True)
    log=io.StringIO(); handler=logging.StreamHandler(log)
    llm_logger=logging.getLogger('app.services.llm_service')
    llm_logger.addHandler(handler); llm_logger.setLevel(logging.INFO)
    original_timeout=settings.LLM_TIMEOUT
    try:
        settings.LLM_TIMEOUT=.01
        evidence['forced_timeout_diagnosis']=request(client,'post','/api/student/diagnosis/explain',student)
        evidence['forced_timeout_chat']=request(client,'post','/api/student/chat/knowledge-point',student,
            json={'message':'请解释学习步骤。','knowledge_point_id':kp,'history':[]})
        evidence['forced_timeout_path']=request(client,'get','/api/student/path/explain',student)
        evidence['forced_timeout_report']=request(client,'get','/api/student/weekly-report',student)
        assert all(evidence[k]['degraded'] for k in ('forced_timeout_diagnosis','forced_timeout_chat',
                                                  'forced_timeout_path','forced_timeout_report'))
        evidence['timeout_log']=log.getvalue().splitlines()
        sensitive=[settings.LLM_API_KEY,student,admin,identities['student']['password'],identities['admin']['password']]
        assert not any(s and s in log.getvalue() for s in sensitive)
        evidence['sensitive_log_check']='PASS：真实故障日志不含API Key、完整Token、临时密码；单元测试另覆盖异常原文中的秘密和输入'
    finally:
        settings.LLM_TIMEOUT=original_timeout; llm_logger.removeHandler(handler)
    # 恢复配置后原缓存立即失效，留给 UI 的是正常模型总结。
    evidence['report_recovered']=request(client,'get','/api/student/weekly-report',student)
    evidence['permissions']={}
    for label,path,token in [('anonymous','/api/student/weekly-report',''),
        ('student_admin','/api/admin/ai-reports/weekly',student),('admin_student','/api/student/weekly-report',admin)]:
        response=client.get(path,headers={'Authorization':f'Bearer {token}'} if token else {})
        evidence['permissions'][label]={'http':response.status_code,'code':response.json()['code']}
    evidence['normal_model_success']=all(not evidence[k]['degraded'] for k in
        ('normal_diagnosis','normal_chat','normal_general_chat','normal_path','report_recovered'))
    EVIDENCE.write_text(json.dumps(evidence,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps({'normal_model_success':evidence['normal_model_success'],'cache_hit':True,
        'cache_invalidated':True,'timeout_degraded':True,'evidence':str(EVIDENCE)},ensure_ascii=False),flush=True)


def cleanup() -> None:
    """只删除记录文件中两个临时身份关联的数据，保留所有已有业务数据。"""
    identities=json.loads(SESSION.read_text(encoding='utf-8'))
    users=[identities[r]['user_id'] for r in ('student','admin')]
    conn=get_connection()
    deleted={}
    try:
        cursor=conn.cursor()
        for table in ('weekly_reports','diagnosis_sessions','user_kp_mastery','answer_records','check_ins','user_achievements','users'):
            cursor.execute(f'DELETE FROM {table} WHERE user_id IN (?,?)',tuple(users))
            deleted[table]=cursor.rowcount
        conn.commit()
        remaining=cursor.execute('SELECT COUNT(*) FROM users WHERE user_id IN (?,?)',tuple(users)).fetchone()[0]
        assert remaining==0
    except Exception:
        conn.rollback(); raise
    finally: conn.close()
    evidence=json.loads(EVIDENCE.read_text(encoding='utf-8')) if EVIDENCE.exists() else {}
    evidence['cleanup']={'deleted':deleted,'remaining_users':remaining}
    EVIDENCE.write_text(json.dumps(evidence,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    SESSION.unlink()
    print(json.dumps({'cleanup':deleted,'remaining_users':remaining}),flush=True)


if __name__=='__main__':
    if sys.argv[1]=='prepare': asyncio.run(prepare())
    elif sys.argv[1]=='cleanup': cleanup()
    else: raise SystemExit('prepare or cleanup required')
