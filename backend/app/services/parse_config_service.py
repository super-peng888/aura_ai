"""系统级解析配置服务（VLM 视觉解析模型）：DB 覆盖 + Redis 缓存 + env 兜底。

仿 RetrievalConfigService：
1. 内置默认值取 settings.VLM_*（env）
2. 查 Redis 缓存（key: parse_config:system，TTL 300s）
3. 缓存未命中 → 查 system_parse_config 单行，非 NULL 字段覆盖
4. 配置更新（save）后 invalidate_cache 清除缓存

vlm_api_key 使用 Fernet 加密存储（复用 app.services.llm_service 的加解密工具）：
- resolve() 返回解密后的运行时配置，供 document_parse_service 注入
  ParseStrategyConfig.vlm_config（sync / async / preview 三路径统一）；
- get_for_api() 仅返回掩码与"是否已配置"标记，不明文外发。
"""

from app.config import get_settings
from app.db.base import AsyncSessionLocal
from app.db.models import SystemParseConfig
from app.db.repository import parse_config_repo
from app.services.llm_service import decrypt_api_key, encrypt_api_key
from app.utils.cache import cache_get_or_set, cache_delete

settings = get_settings()

# 数值/字符串字段：DB 非 NULL 时覆盖内置默认（api_key 单独处理加解密）
_OVERRIDE_FIELDS = ("vlm_model", "vlm_base_url", "vlm_detail_level", "vlm_max_tokens")

_DEFAULT_VLM_MODEL = "qwen3-vl-flash"


def _mask_api_key(api_key: str) -> str:
    """API Key 掩码回显（前 4 后 4）。"""
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "****"
    return f"{api_key[:4]}****{api_key[-4:]}"


class ParseConfigService:
    """解析系统级解析配置，返回生效配置字典。"""

    CACHE_KEY = "parse_config:system"
    CACHE_TTL = 300

    @staticmethod
    def _defaults() -> dict:
        """内置默认值（来自 env VLM_*）。"""
        return {
            "vlm_model": settings.VLM_MODEL or _DEFAULT_VLM_MODEL,
            "vlm_base_url": settings.VLM_API_BASE,
            "vlm_api_key": settings.VLM_API_KEY,
            "vlm_detail_level": getattr(settings, "VLM_DETAIL_LEVEL", "high") or "high",
            "vlm_max_tokens": 4096,
        }

    @classmethod
    async def resolve(cls) -> dict:
        """解析生效的运行时配置（vlm_api_key 已解密），供解析流水线使用。"""
        async def _fetch_from_db() -> dict:
            cfg = cls._defaults()
            async with AsyncSessionLocal() as session:
                row = await parse_config_repo.get_singleton(session)
            if row is None:
                return cfg
            for field in _OVERRIDE_FIELDS:
                value = getattr(row, field)
                if value is not None:
                    cfg[field] = value
            if row.vlm_api_key:
                cfg["vlm_api_key"] = decrypt_api_key(row.vlm_api_key)
            return cfg

        try:
            return await cache_get_or_set(
                cls.CACHE_KEY,
                _fetch_from_db,
                ttl=cls.CACHE_TTL,
                prefix="",
            ) or cls._defaults()
        except Exception as e:
            print(f"[ParseConfigService] resolve error: {e}")
            return cls._defaults()

    @classmethod
    async def resolve_vlm_for_strategy(cls) -> dict:
        """返回注入 ParseStrategyConfig.vlm_config 的运行时 VLM 配置。"""
        cfg = await cls.resolve()
        return {
            "model": cfg["vlm_model"],
            "base_url": cfg["vlm_base_url"],
            "api_key": cfg["vlm_api_key"],
            "detail": cfg["vlm_detail_level"],
            "max_tokens": cfg["vlm_max_tokens"],
        }

    @classmethod
    async def invalidate_cache(cls) -> None:
        """配置更新后清除 Redis 缓存。"""
        try:
            await cache_delete(cls.CACHE_KEY, prefix="")
        except Exception as e:
            print(f"[ParseConfigService] invalidate cache error: {e}")

    @classmethod
    async def get_for_api(cls) -> dict:
        """返回给前端的配置（api_key 掩码，不明文外发）。"""
        cfg = await cls.resolve()
        return {
            "vlm_model": cfg["vlm_model"],
            "vlm_base_url": cfg["vlm_base_url"],
            "vlm_api_key_masked": _mask_api_key(cfg["vlm_api_key"]),
            "vlm_api_key_configured": bool(cfg["vlm_api_key"]),
            "vlm_detail_level": cfg["vlm_detail_level"],
            "vlm_max_tokens": cfg["vlm_max_tokens"],
        }

    @classmethod
    async def save(cls, data: dict) -> dict:
        """整体 upsert 配置。vlm_api_key 留空（None/空串）时保持既有值不变。"""
        async with AsyncSessionLocal() as session:
            existing = await parse_config_repo.get_singleton(session)
            api_key_plain = (data.get("vlm_api_key") or "").strip()
            if api_key_plain:
                api_key_to_store = encrypt_api_key(api_key_plain)
            elif existing is not None:
                api_key_to_store = existing.vlm_api_key
            else:
                api_key_to_store = None

            config = SystemParseConfig(
                vlm_model=(data.get("vlm_model") or "").strip() or _DEFAULT_VLM_MODEL,
                vlm_base_url=(data.get("vlm_base_url") or "").strip() or settings.VLM_API_BASE,
                vlm_api_key=api_key_to_store,
                vlm_detail_level=data.get("vlm_detail_level") or "high",
                vlm_max_tokens=int(data.get("vlm_max_tokens") or 4096),
            )
            await parse_config_repo.upsert(session, config)
            await session.commit()

        await cls.invalidate_cache()
        return await cls.get_for_api()


parse_config_service = ParseConfigService()
