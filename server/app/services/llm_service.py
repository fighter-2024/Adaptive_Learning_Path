"""
大模型统一调用服务（AI开发总则第八章「AI 大模型调用规范」）

- 所有大模型调用必须走本模块，不散落在各处业务代码里；
- 统一走 OpenAI 兼容 /chat/completions 接口（DeepSeek / 通义千问兼容模式）；
- 必须设置超时：默认 30 秒（settings.LLM_TIMEOUT）；
- 失败最多重试 2 次（总则原文）；
- 返回内容做基本校验：非空、长度截断到上限，防止异常输出污染前端；
- 任何失败都返回 None 并记录日志，由调用方提供降级内容，不阻塞业务流程；
- 密钥/接口地址全部来自 .env（settings），禁止硬编码。
"""

import logging
from typing import Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_LLM_MAX_RETRIES = 2  # 失败后最多重试 2 次（总则：重试最多 2 次）
_LLM_MAX_RESPONSE_CHARS = 8000  # 大模型返回长度上限，超出截断（防异常输出）


async def chat_completion(
    messages: List[Dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> Optional[str]:
    """调用 OpenAI 兼容大模型接口并返回文本内容

    Args:
        messages: 对话消息列表，每条含 role(system/user/assistant) 与 content
        temperature: 采样温度，0.0~2.0
        max_tokens: 生成 token 上限

    Returns:
        大模型返回的文本；未配置密钥/接口地址、调用失败、超时、
        返回内容异常时返回 None（调用方应准备降级内容）

    Note:
        本函数自身吞掉所有异常（记录日志），保证业务方可以无条件
        调用并做降级，符合总则「调用失败时返回降级内容，不阻塞业务流程」。
    """
    if not settings.LLM_API_KEY or not settings.LLM_API_BASE:
        logger.warning(
            "LLM 未配置（LLM_API_KEY / LLM_API_BASE 为空），跳过调用，由调用方降级"
        )
        return None

    url = settings.LLM_API_BASE.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {settings.LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    last_error: Optional[Exception] = None
    total_attempts = _LLM_MAX_RETRIES + 1
    for attempt in range(total_attempts):  # 首次调用 + 最多 2 次重试
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT) as client:
                response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            text = (content or "").strip()
            if not text:
                raise ValueError("大模型返回内容为空")
            if len(text) > _LLM_MAX_RESPONSE_CHARS:
                logger.warning(
                    "大模型返回过长（%d 字符），截断到 %d 字符",
                    len(text),
                    _LLM_MAX_RESPONSE_CHARS,
                )
                text = text[:_LLM_MAX_RESPONSE_CHARS]
            return text
        except httpx.TimeoutException as e:
            last_error = e
            logger.warning(
                "大模型调用超时（第 %d/%d 次）: %s", attempt + 1, total_attempts, e
            )
        except Exception as e:
            last_error = e
            logger.warning(
                "大模型调用失败（第 %d/%d 次）: %s", attempt + 1, total_attempts, e
            )

    logger.error(
        "大模型调用最终失败（已重试 %d 次），返回 None 由调用方降级: %s",
        _LLM_MAX_RETRIES,
        last_error,
    )
    return None
