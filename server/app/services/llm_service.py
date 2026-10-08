"""统一模型调用：总超时、有限重试、输出校验与无敏感内容日志。"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional
import httpx
from app.config import settings

logger = logging.getLogger(__name__)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
_LLM_MAX_RETRIES = 2


@dataclass
class CompletionResult:
    """模型结果及固定分类的降级原因。"""
    content: Any = None
    reason: Optional[str] = None


async def complete(messages: list[dict[str, str]], temperature: float = .7,
                   max_tokens: int = 1024,
                   validator: Optional[Callable[[str], Any]] = None) -> CompletionResult:
    """所有尝试共享总超时预算，日志只记录状态与尝试次数。"""
    if (settings.LLM_PROVIDER not in {'deepseek', 'qwen'} or not settings.LLM_API_KEY
            or not settings.LLM_API_BASE or not settings.LLM_MODEL):
        logger.info('LLM outcome=unconfigured attempts=0')
        return CompletionResult(reason='模型未配置，已使用规则内容')
    if any(m.get('role') not in {'system', 'user', 'assistant'}
           or not isinstance(m.get('content'), str) for m in messages):
        return CompletionResult(reason='模型输入无效，已使用规则内容')
    if sum(len(m['content']) for m in messages) > 64000:
        return CompletionResult(reason='模型上下文过长，已使用规则内容')
    url = settings.LLM_API_BASE.rstrip('/') + '/chat/completions'
    payload = {'model': settings.LLM_MODEL, 'messages': messages,
               'temperature': temperature, 'max_tokens': max_tokens}
    headers = {'Authorization': f'Bearer {settings.LLM_API_KEY}'}
    deadline = time.monotonic() + max(.01, float(settings.LLM_TIMEOUT))
    reason = '模型服务不可用，已使用规则内容'
    for attempt in range(_LLM_MAX_RETRIES + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return CompletionResult(reason='模型超时，已使用规则内容')
        try:
            async with httpx.AsyncClient(timeout=remaining, follow_redirects=False) as client:
                response = await asyncio.wait_for(client.post(url, json=payload, headers=headers), remaining)
            response.raise_for_status()
            content = response.json()['choices'][0]['message']['content']
            if not isinstance(content, str) or not content.strip() or len(content) > 8000:
                raise ValueError('invalid_output')
            value = validator(content.strip()) if validator else content.strip()
            logger.info('LLM outcome=success attempt=%d', attempt + 1)
            return CompletionResult(content=value)
        except (httpx.TimeoutException, asyncio.TimeoutError):
            reason, category = '模型超时，已使用规则内容', 'timeout'
        except (ValueError, TypeError, KeyError, IndexError):
            reason, category = '模型返回格式异常，已使用规则内容', 'invalid_output'
        except Exception:
            reason, category = '模型服务不可用，已使用规则内容', 'service_error'
        logger.warning('LLM outcome=%s attempt=%d', category, attempt + 1)
    return CompletionResult(reason=reason)


async def chat_completion(messages: list[dict[str, str]], temperature: float = .7,
                          max_tokens: int = 1024) -> Optional[str]:
    """保留 M8 文本调用契约，底层统一调用 complete。"""
    return (await complete(messages, temperature, max_tokens)).content


def parse_json_object(text: str) -> dict:
    """解析对象，允许外层 Markdown JSON 围栏。"""
    if text.startswith('```json\n') and text.endswith('```'):
        text = text[8:-3].strip()
    elif text.startswith('```\n') and text.endswith('```'):
        text = text[4:-3].strip()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError('invalid_object')
    return value
