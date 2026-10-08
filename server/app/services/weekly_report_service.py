"""真实周报统计与持久化摘要缓存；每次读取复核源数据。"""
import asyncio
import hashlib
import json
import re
import uuid
from datetime import date, datetime, time, timedelta
from app.config import settings
from app.config.prompts import WEEKLY_SYSTEM_PROMPT, build_ai_context
from app.db.sqlserver import get_connection, get_local_now
from app.models.ai import WeeklyReport
from app.services.ai_service import _load_knowledge, _text_field
from app.services.llm_service import complete, parse_json_object, CompletionResult

WEEKLY_VALIDATOR_VERSION = 'm9-r3-duration-facts-v1'


class InvalidWeekError(ValueError):
    """用户选择的日期不符合周报范围。"""


def _duration_fact(seconds: int, minutes: int) -> str:
    """生成可供模型引用的作答时长事实，明确零值与不足一分钟。"""
    if seconds <= 0:
        return '没有有效的作答时长记录，按整分钟显示为0分钟。'
    if seconds < 60:
        return f'已记录作答时长{seconds}秒，不足1分钟，按整分钟显示为0分钟。'
    return f'已记录作答时长{seconds}秒，按整分钟向下取整显示为{minutes}分钟。'


def _normalize_summary(summary: str) -> str:
    """压缩空白，令中文事实校验不受模型标点/空格差异影响。"""
    return re.sub(r'\s+', '', summary)


def _contains_missing_duration_claim(summary: str) -> bool:
    """识别把正值作答时长误说成缺失的常见中文变体。"""
    text = _normalize_summary(summary)
    return bool(re.search(
        r'(?:暂无|没有|无|未包含|未记录|没有记录|未有).{0,10}'
        r'(?:有效|可用)?(?:的)?(?:作答)?时长(?:记录|数据)?',
        text,
    ))


def _duration_fact_segment(summary: str) -> str:
    """取建议/行动句之前的事实段，避免建议句中的秒数冒充本周统计。"""
    text = _normalize_summary(summary)
    positions = [text.find(marker) for marker in ('建议', '下周', '请在', '推荐')]
    positions = [position for position in positions if position >= 0]
    return text[:min(positions)] if positions else text


def _has_recorded_duration_fact(summary: str, seconds: int, minutes: int) -> bool:
    """要求正值时长在事实段中被承认为已记录，并带有对应量级。"""
    if seconds <= 0:
        return True
    fact = _duration_fact_segment(summary)
    if '作答时长' not in fact:
        return False
    recorded = (
        '已记录' in fact or '记录了' in fact or '记录的' in fact or
        bool(re.search(r'(?:本周|本次|总计|累计)[^。；;]{0,16}作答时长', fact)) or
        bool(re.search(r'作答时长(?:为|是|共计)', fact))
    )
    if not recorded:
        return False
    amount = str(seconds)
    minute = str(minutes)
    if seconds < 60:
        return bool(
            re.search(rf'作答时长[^。；;]{{0,24}}{amount}秒', fact) or
            re.search(rf'{amount}秒[^。；;]{{0,24}}作答时长', fact) or
            ('不足1分钟' in fact and ('按整分钟' in fact or '显示为0分钟' in fact))
        )
    return bool(
        re.search(rf'作答时长[^。；;]{{0,24}}{amount}秒', fact) or
        re.search(rf'{amount}秒[^。；;]{{0,24}}作答时长', fact) or
        re.search(rf'作答时长[^。；;]{{0,24}}{minute}分钟', fact) or
        re.search(rf'{minute}分钟[^。；;]{{0,24}}作答时长', fact)
    )


def resolve_week(week_start: date | None) -> date:
    """周一且不可未来；业务时间遵循现有 SQL 本地时间口径。"""
    today = get_local_now().date()
    week = week_start or today - timedelta(days=today.weekday())
    if week.weekday() != 0 or week > today:
        raise InvalidWeekError('请选择非未来的周一日期')
    return week


def _db_sources(user_id: str, week: date) -> dict:
    """当前用户的答题汇总、周前基线及周内诊断；不查询答案或身份。"""
    start = datetime.combine(week, time.min)
    end = start + timedelta(days=7)
    conn = get_connection()
    try:
        c = conn.cursor()
        # 同一事务内串行读取，不将连接持有至模型调用。
        c.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
        row = c.execute('SELECT COUNT_BIG(*), COALESCE(SUM(CAST(is_correct AS BIGINT)),0), '
            'COALESCE(SUM(CAST(CASE WHEN time_spent > 0 THEN time_spent ELSE 0 END AS BIGINT)),0) '
            'FROM answer_records WHERE user_id=? AND created_at>=? AND created_at<?',
            (user_id, start, end)).fetchone()
        before = c.execute('SELECT TOP 1 alpha_vector FROM diagnosis_sessions '
            'WHERE user_id=? AND diagnosed_at<? ORDER BY diagnosed_at DESC,id DESC',
            (user_id, start)).fetchone()
        during = c.execute('SELECT alpha_vector FROM diagnosis_sessions '
            'WHERE user_id=? AND diagnosed_at>=? AND diagnosed_at<? ORDER BY diagnosed_at,id',
            (user_id, start, end)).fetchall()
        current = []
        if start <= get_local_now() < end:
            current = c.execute('SELECT knowledge_point_id,mastery_probability FROM user_kp_mastery '
                'WHERE user_id=? ORDER BY knowledge_point_id', (user_id,)).fetchall()
        baseline = json.loads(before[0]) if before else {}
        snapshots = [json.loads(r[0]) for r in during]
        if current:
            snapshots.append({str(r[0]): float(r[1]) for r in current})
        return {'questions_done': int(row[0]), 'correct_count': int(row[1]),
                'time_seconds': int(row[2]), 'baseline': baseline, 'snapshots': snapshots}
    finally:
        conn.close()


def calculate_stats(source: dict) -> dict:
    """保留重复作答，并从快照阈值变化推断新掌握，末状态必须仍掌握。"""
    previous = dict(source['baseline'])
    crossed = set()
    for snapshot in source['snapshots']:
        for kp, probability in snapshot.items():
            if probability >= .8 and previous.get(kp, 0) < .8 and source['baseline'].get(kp, 0) < .8:
                crossed.add(kp)
        previous.update(snapshot)
    total = source['questions_done']
    return {'questions_done': total,
            'correct_rate': source['correct_count'] / total if total else 0,
            'study_time_minutes': source['time_seconds'] // 60,
            'new_mastered_ids': sorted(k for k in crossed if previous.get(k, 0) >= .8),
            'still_weak_ids': sorted(k for k, v in previous.items() if v < .4)}


def _db_read_cache(user_id: str, week: date) -> dict | None:
    """读取该学生该周的摘要缓存与降级状态。"""
    conn = get_connection()
    try:
        r = conn.cursor().execute('SELECT source_digest,ai_summary,generated_at,degraded,degraded_reason '
            'FROM weekly_reports WHERE user_id=? AND week_start=?', (user_id, week)).fetchone()
        return dict(zip(('digest', 'summary', 'generated_at', 'degraded', 'reason'), r)) if r else None
    finally:
        conn.close()


def _db_save_cache(user_id: str, week: date, digest: str, report: WeeklyReport) -> None:
    """锁定唯一用户/周键后更新或插入，失败回滚，不删除既有报告。"""
    conn = get_connection()
    try:
        c = conn.cursor()
        existing = c.execute('SELECT id FROM weekly_reports WITH (UPDLOCK,HOLDLOCK) '
            'WHERE user_id=? AND week_start=?', (user_id, week)).fetchone()
        values = (date.fromisoformat(report.week_end), report.questions_done, report.correct_rate, report.study_time_minutes,
            json.dumps([k.model_dump() for k in report.new_mastered], ensure_ascii=False),
            json.dumps([k.model_dump() for k in report.still_weak], ensure_ascii=False), report.ai_summary,
            datetime.fromisoformat(report.generated_at), digest, int(report.degraded), report.degraded_reason)
        if existing:
            c.execute('UPDATE weekly_reports SET week_end=?,questions_done=?,correct_rate=?,study_time_minutes=?,'
                'new_mastered=?,still_weak=?,ai_summary=?,generated_at=?,source_digest=?,degraded=?,degraded_reason=? '
                'WHERE id=?', (*values, existing[0]))
        else:
            c.execute('INSERT INTO weekly_reports (week_end,questions_done,correct_rate,study_time_minutes,'
                'new_mastered,still_weak,ai_summary,generated_at,source_digest,degraded,degraded_reason,'
                'report_id,user_id,week_start) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (*values, 'wr_' + uuid.uuid4().hex[:24], user_id, week))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def get_weekly_report(user_id: str, week_start: date | None = None,
                            generate_summary: bool = True) -> WeeklyReport:
    """复核真实数据后使用有效缓存；模型只能生成总结字段。"""
    week = resolve_week(week_start)
    source = await asyncio.to_thread(_db_sources, user_id, week)
    stats = calculate_stats(source)
    new_ids, weak_ids = stats.pop('new_mastered_ids'), stats.pop('still_weak_ids')
    ids = sorted(set(new_ids + weak_ids))
    points = await asyncio.to_thread(_load_knowledge, ids=ids) if ids else []
    names = {p['id']: p['name'] for p in points}
    stats['new_mastered'] = [{'id': k, 'name': names.get(k, k)} for k in new_ids]
    stats['still_weak'] = [{'id': k, 'name': names.get(k, k)} for k in weak_ids]
    stats.update(week_start=week.isoformat(), week_end=(week + timedelta(days=6)).isoformat())
    # 配置身份只用于不可逆摘要，绝不持久化或传给模型。
    fingerprint = {'source': source, 'stats': stats, 'prompt': WEEKLY_SYSTEM_PROMPT,
        'validator_version': WEEKLY_VALIDATOR_VERSION,
        'config': [settings.LLM_PROVIDER, settings.LLM_MODEL, settings.LLM_API_BASE,
                   hashlib.sha256(settings.LLM_API_KEY.encode()).hexdigest(), settings.LLM_TIMEOUT]}
    digest = hashlib.sha256(json.dumps(fingerprint, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    cache = await asyncio.to_thread(_db_read_cache, user_id, week)
    now = get_local_now()
    if cache and cache['digest'] == digest and isinstance(cache['summary'], str) and cache['summary'].strip():
        age = (now - cache['generated_at']).total_seconds()
        if 0 <= age < (60 if cache['degraded'] else 86400):
            return WeeklyReport(**stats, ai_summary=cache['summary'], generated_at=cache['generated_at'].isoformat(),
                cached=True, degraded=bool(cache['degraded']), degraded_reason=cache['reason'])

    raw_seconds = source['time_seconds']

    def validate(text: str) -> str:
        """只接受非空总结，不接受模型统计作为报告数据。"""
        summary = _text_field(parse_json_object(text), 'ai_summary')
        if '总学习时' in summary or '总学习时间' in summary or '平台上的总' in summary:
            raise ValueError('unavailable_total_learning_time')
        if raw_seconds > 0 and _contains_missing_duration_claim(summary):
            raise ValueError('contradictory_duration_fact')
        if raw_seconds > 0 and not _has_recorded_duration_fact(
            summary, raw_seconds, stats['study_time_minutes']
        ):
            raise ValueError('missing_recorded_duration_fact')
        return summary

    model_stats = {**stats, 'new_mastered': [k['name'] for k in stats['new_mastered']],
                   'still_weak': [k['name'] for k in stats['still_weak']],
                   'study_time_seconds': raw_seconds,
                   'study_time_fact': _duration_fact(raw_seconds, stats['study_time_minutes'])}
    result = (await complete([{'role': 'system', 'content': WEEKLY_SYSTEM_PROMPT},
        {'role': 'user', 'content': build_ai_context(model_stats)}], validator=validate)
        if generate_summary else CompletionResult(reason='报告数据已更新，暂用规则总结；学生打开周报时可重新生成 AI 总结'))
    fallback = (f"本周共作答 {stats['questions_done']} 次，正确率 {stats['correct_rate']:.0%}，"
        f"{_duration_fact(raw_seconds, stats['study_time_minutes'])}"
        f"已记录的新掌握知识点 {len(stats['new_mastered'])} 个，薄弱知识点 {len(stats['still_weak'])} 个。"
        + ('先从学习总览选择知识点并完成练习，再运行诊断。' if not stats['questions_done']
           else '下周优先复习薄弱知识的前置内容，完成练习后重新诊断。'))
    report = WeeklyReport(**stats, ai_summary=result.content or fallback, generated_at=get_local_now().replace(microsecond=0).isoformat(),
        degraded=result.content is None, degraded_reason=result.reason)
    if generate_summary:
        await asyncio.to_thread(_db_save_cache, user_id, week, digest, report)
    return report


def _db_report_list(page: int, page_size: int, student_id: str | None, week: date | None) -> tuple:
    """分页读取已生成报告的键，使用参数绑定过滤。"""
    clauses = ["u.role='student'"]
    params = []
    if student_id:
        clauses.append('w.user_id=?')
        params.append(student_id)
    if week:
        clauses.append('w.week_start=?')
        params.append(week)
    where = ' AND '.join(clauses)
    conn = get_connection()
    try:
        c = conn.cursor()
        total = c.execute('SELECT COUNT(*) FROM weekly_reports w JOIN users u ON u.user_id=w.user_id WHERE ' + where,
                          tuple(params)).fetchone()[0]
        rows = c.execute('SELECT w.report_id,w.user_id,u.name,w.week_start FROM weekly_reports w '
            'JOIN users u ON u.user_id=w.user_id WHERE ' + where +
            ' ORDER BY w.week_start DESC,w.id DESC OFFSET ? ROWS FETCH NEXT ? ROWS ONLY',
            (*params, (page-1)*page_size, page_size)).fetchall()
        return total, [tuple(r) for r in rows]
    finally:
        conn.close()


async def list_weekly_reports(page: int, page_size: int, student_id: str | None,
                              week_start: date | None) -> dict:
    """管理端查看已生成的报告；逐项复核缓存后展示。"""
    week = resolve_week(week_start) if week_start else None
    total, rows = await asyncio.to_thread(_db_report_list, page, page_size, student_id, week)
    async def item(row: tuple) -> dict:
        """补全单个报告。"""
        report = await get_weekly_report(row[1], row[3], generate_summary=False)
        return {**report.model_dump(), 'report_id': row[0], 'student_id': row[1], 'student_name': row[2]}
    # 控制第三方调用并发；管理端每页最多20项。
    semaphore = asyncio.Semaphore(3)
    async def limited(row: tuple) -> dict:
        """最多三项同时刷新。"""
        async with semaphore:
            return await item(row)
    return {'list': await asyncio.gather(*(limited(r) for r in rows)), 'total': total,
            'page': page, 'page_size': page_size}
