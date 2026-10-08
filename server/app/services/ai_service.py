"""诊断与答疑解释层，不修改学习数据。"""
import asyncio
import re
from app.config.prompts import DIAGNOSIS_SYSTEM_PROMPT, CHAT_SYSTEM_PROMPT, build_ai_context
from app.db import get_driver
from app.models.ai import ChatRequest, ChatReply, KnowledgeChatReply, DiagnosisExplain
from app.services.diagnosis_service import get_latest_diagnosis
from app.services.llm_service import complete, parse_json_object


class KnowledgeNotFoundError(Exception):
    """指定知识点不存在。"""


def _load_knowledge(message: str = '', kp_id: str | None = None,
                    ids: list[str] | None = None) -> list[dict]:
    """只查询必要知识资料，不读取身份和题目答案。"""
    with get_driver().session() as session:
        if kp_id or ids is not None:
            result = session.run('MATCH (k:KnowledgePoint) WHERE k.id IN $ids '
                'RETURN k.id AS id, k.name AS name, k.description AS description ORDER BY k.id',
                ids=[kp_id] if kp_id else ids)
        else:
            tokens = [t for t in re.split(r'[\s，。？、和与的]+', message) if len(t) >= 2][:8]
            result = session.run('MATCH (k:KnowledgePoint) WHERE $message CONTAINS k.name '
                'OR any(t IN $tokens WHERE k.name CONTAINS t) '
                'RETURN k.id AS id, k.name AS name, k.description AS description '
                'ORDER BY k.id LIMIT 8', message=message, tokens=tokens)
        return [{'id': str(r['id']), 'name': str(r['name']),
                 'description': str(r['description'] or '')[:1600]} for r in result]


def _text_field(data: dict, key: str, limit: int = 1000) -> str:
    """空白、超长及类型错误输出必须降级。"""
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('invalid_text')
    return value.strip()


async def explain_diagnosis(user_id: str) -> DiagnosisExplain:
    """优势与薄弱项由真实诊断概率阈值确定。"""
    diagnosis = await get_latest_diagnosis(user_id)
    if not diagnosis:
        return DiagnosisExplain(explanation='尚无认知诊断记录，暂时无法判断优势与薄弱知识点。',
            suggestion='先在学习总览选择知识点并完成练习，再返回诊断页运行诊断。',
            degraded=True, degraded_reason='尚无诊断数据，已使用规则建议')
    points = await asyncio.to_thread(_load_knowledge, ids=list(diagnosis.alpha_vector))
    names = {p['id']: p['name'] for p in points}
    probabilities = diagnosis.alpha_vector
    strengths = [names.get(k, k) for k, v in probabilities.items() if v >= .8]
    weaknesses = [names.get(k, k) for k, v in probabilities.items() if v < .4]
    fallback = f'本次诊断记录了 {len(probabilities)} 个知识点，其中 {len(strengths)} 个已掌握，{len(weaknesses)} 个需要加强。掌握概率是模型估计，可通过后续练习继续验证。'
    suggestion = ('先复习「' + '、'.join(weaknesses[:3]) + '」的前置知识，再练习并重新诊断。'
                  if weaknesses else '按推荐路径继续学习，通过新题检验掌握情况。')

    def validate(text: str) -> dict:
        """校验模型诊断结构。"""
        data = parse_json_object(text)
        return {k: _text_field(data, k) for k in ('explanation', 'suggestion')}

    result = await complete([{'role': 'system', 'content': DIAGNOSIS_SYSTEM_PROMPT},
        {'role': 'user', 'content': build_ai_context({'knowledge_points': [
            {'name': names.get(k, k), 'mastery_probability': v} for k, v in probabilities.items()][:200],
            'strengths': strengths[:30], 'weaknesses': weaknesses[:30]})}], validator=validate)
    return DiagnosisExplain(**(result.content or {'explanation': fallback, 'suggestion': suggestion}),
        strengths=strengths, weaknesses=weaknesses, degraded=result.content is None,
        degraded_reason=result.reason)


async def answer_chat(request: ChatRequest, kp_id: str | None = None) -> ChatReply:
    """知识点引用限定为已读取的真实图谱资料。"""
    points = await asyncio.to_thread(_load_knowledge, request.message, kp_id)
    if kp_id and not points:
        raise KnowledgeNotFoundError()
    allowed = {p['id']: p for p in points}

    def validate(text: str) -> dict:
        """拒绝格式错误或虚构引用。"""
        data = parse_json_object(text)
        reply = _text_field(data, 'reply', 2000)
        ids = data.get('related_knowledge_point_ids')
        if not isinstance(ids, list) or len(ids) > 5 or any(not isinstance(k, str) or k not in allowed for k in ids):
            raise ValueError('invalid_references')
        return {'reply': reply, 'ids': list(dict.fromkeys(ids))}

    messages = [{'role': 'system', 'content': CHAT_SYSTEM_PROMPT},
                {'role': 'system', 'content': build_ai_context({'knowledge_points': points})}]
    messages += [m.model_dump() for m in request.history]
    messages += [{'role': 'user', 'content': request.message}]
    result = await complete(messages, validator=validate, max_tokens=1800)
    if result.content:
        reply, ids = result.content['reply'], result.content['ids']
    else:
        ids = list(allowed)[:5]
        reply = ('目前提供知识资料与学习步骤：\n' + '\n'.join(
            f"{p['name']}：{p['description'] or '可打开知识点详情复习。'}" for p in points[:2])
            + '\n先梳理定义与前置知识，再做相关练习核对每一步。可以补充具体算式继续讨论。'
            if points else '暂时无法提供模型答疑。请补充知识点名称或具体算式，或从学习总览打开知识点后使用“问 AI”，查看对应知识资料与练习入口。')
    fields = dict(reply=reply, related_knowledge_points=[{'id': k, 'name': allowed[k]['name']} for k in ids],
        degraded=result.content is None, degraded_reason=result.reason)
    return KnowledgeChatReply(**fields, knowledge_point_name=points[0]['name']) if kp_id else ChatReply(**fields)
