"""Redis 缓存工具封装。

提供统一的异步缓存接口，支持 JSON 序列化、TTL 和键前缀。
"""

import json
import pickle
from typing import Any, Optional, Union

from redis.asyncio import Redis
from app.config import get_settings

_settings = get_settings()

# 全局 Redis 连接实例（懒加载）
_redis_client: Optional[Redis] = None


def get_redis() -> Redis:
    """获取或创建 Redis 连接实例。"""
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis(
            host=_settings.REDIS_HOST,
            port=_settings.REDIS_PORT,
            db=_settings.REDIS_DB,
            password=_settings.REDIS_PASSWORD or None,
            decode_responses=True,
        )
    return _redis_client


async def close_redis() -> None:
    """关闭 Redis 连接。"""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None


# 默认键前缀，避免与其他应用冲突
DEFAULT_PREFIX = "aura:"


def _build_key(key: str, prefix: Optional[str] = None) -> str:
    return f"{prefix or DEFAULT_PREFIX}{key}"


async def cache_get(key: str, prefix: Optional[str] = None) -> Any:
    """从缓存获取值，自动反序列化 JSON。"""
    r = get_redis()
    raw = await r.get(_build_key(key, prefix))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


async def cache_set(
    key: str,
    value: Any,
    ttl: int = 300,
    prefix: Optional[str] = None,
) -> None:
    """写入缓存，自动序列化为 JSON。"""
    r = get_redis()
    if isinstance(value, (dict, list, tuple)):
        raw = json.dumps(value, default=str)
    elif isinstance(value, str):
        raw = value
    else:
        raw = json.dumps(value, default=str)
    await r.setex(_build_key(key, prefix), ttl, raw)


async def cache_delete(key: str, prefix: Optional[str] = None) -> None:
    """删除指定缓存键。"""
    r = get_redis()
    await r.delete(_build_key(key, prefix))


async def cache_get_or_set(
    key: str,
    factory,
    ttl: int = 300,
    prefix: Optional[str] = None,
) -> Any:
    """缓存读取或写入（cache-aside 模式）。

    如果缓存命中直接返回；否则调用 factory 获取数据，写入缓存后返回。
    factory 必须是可 await 的协程函数。
    """
    cached = await cache_get(key, prefix)
    if cached is not None:
        return cached
    value = await factory()
    if value is not None:
        await cache_set(key, value, ttl, prefix)
    return value
