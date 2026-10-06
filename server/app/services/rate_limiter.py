"""
请求速率限制服务（防暴力破解）

纯内存滑动窗口实现（线程安全，零依赖），供认证接口使用：
- 登录 / 注册按客户端 IP 计数，窗口内超过上限抛出 RateLimitExceededError；
- 阈值与窗口长度读取自 app.config.settings（.env 可配置）；
- 触发限制时记录 warning 日志（审计暴力破解尝试）；
- 测试可用 reset_rate_limits() 清理状态。

说明：单进程内存实现，重启即清零；多实例部署时应替换为
Redis 等共享存储（当前单机部署场景够用）。被限流的请求不计入窗口，
客户端需等待窗口滑动后才能继续尝试。
"""

import logging
import threading
import time
from collections import deque
from typing import Deque, Dict

logger = logging.getLogger(__name__)

# 全局状态：key → 最近请求时间戳队列（线程安全）
_window_lock = threading.Lock()
_hits: Dict[str, Deque[float]] = {}


class RateLimitExceededError(Exception):
    """请求过于频繁，触发速率限制"""


def check_rate_limit(key: str, max_attempts: int, window_seconds: int) -> None:
    """检查给定 key 在滑动窗口内的请求次数是否超限（超限抛异常）

    Args:
        key: 限流键（如 "login:127.0.0.1"）
        max_attempts: 窗口内允许的最大请求次数
        window_seconds: 滑动窗口长度（秒）

    Raises:
        RateLimitExceededError: 窗口内请求次数已达上限
    """
    if max_attempts <= 0 or window_seconds <= 0:
        # 关闭限流的配置（非正数视为不限制），仅记录一次说明日志
        logger.debug("速率限制未启用: key=%s", key)
        return

    now = time.monotonic()
    with _window_lock:
        hits = _hits.setdefault(key, deque())
        # 清理窗口外的过期时间戳
        while hits and now - hits[0] >= window_seconds:
            hits.popleft()
        if len(hits) >= max_attempts:
            logger.warning(
                "触发速率限制: key=%s，窗口 %d 秒内已请求 %d 次（上限 %d）",
                key,
                window_seconds,
                len(hits),
                max_attempts,
            )
            raise RateLimitExceededError("请求过于频繁，请稍后再试")
        hits.append(now)

    # 空闲 key 惰性清理，避免字典无限增长
    with _window_lock:
        empty_keys = [k for k, v in _hits.items() if not v]
        for k in empty_keys:
            _hits.pop(k, None)


def reset_rate_limits() -> None:
    """清空全部限流计数（供单元测试使用，勿在业务代码中调用）"""
    with _window_lock:
        _hits.clear()
    logger.debug("速率限制计数已重置")
