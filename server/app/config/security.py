"""敏感配置和日志脱敏工具。

该模块只负责展示层脱敏，不改变实际配置值。任何管理端配置接口都应使用
``mask_secret`` 生成回显字段，日志则通过 ``SensitiveDataFilter`` 统一处理。
"""

import logging
import re
from typing import Any


def mask_secret(value: str | None, visible_chars: int = 4) -> str:
    """掩码显示密钥，只保留末尾少量字符。

    Args:
        value: 原始密钥；空值表示未配置。
        visible_chars: 最多保留的末尾字符数。

    Returns:
        脱敏后的字符串。短密钥也不会被完整回显。
    """
    if not value:
        return ""
    visible_chars = max(0, min(visible_chars, 8))
    if len(value) <= visible_chars:
        return "*" * max(4, len(value))
    suffix = value[-visible_chars:] if visible_chars else ""
    return "*" * max(4, len(value) - visible_chars) + suffix


_SENSITIVE_VALUE_PATTERNS = (
    re.compile(
        r"(?i)([\"']?authorization[\"']?\s*[:=]\s*[\"']?bearer\s+)[^\"\s,;}]+"
    ),
    re.compile(
        r"(?i)([\"']?(?:api[_-]?key|secret[_-]?key|password|passwd|token|pwd)[\"']?\s*[:=]\s*[\"']?)[^\"\s,;}]+"
    ),
)


def redact_sensitive_text(value: str) -> str:
    """移除日志文本中的常见凭证值。"""

    def replace(match: re.Match[str]) -> str:
        prefix = match.group(1)
        return prefix + "[REDACTED]"

    result = value
    for pattern in _SENSITIVE_VALUE_PATTERNS:
        result = pattern.sub(replace, result)
    return result


class SensitiveDataFilter(logging.Filter):
    """对 logging record 的最终文本做脱敏。"""

    def filter(self, record: logging.LogRecord) -> bool:
        """脱敏后放行日志记录，不因过滤失败阻塞业务日志。"""
        try:
            original = record.getMessage()
            redacted = redact_sensitive_text(original)
            if redacted != original:
                record.msg = redacted
                record.args = ()
        except Exception:
            # 日志脱敏不应反过来影响请求处理。
            return True
        return True


def masked_config_value(value: Any) -> str:
    """将任意配置值规范化为可安全展示的字符串。"""
    return mask_secret(str(value)) if value else ""


__all__ = [
    "SensitiveDataFilter",
    "mask_secret",
    "masked_config_value",
    "redact_sensitive_text",
]
