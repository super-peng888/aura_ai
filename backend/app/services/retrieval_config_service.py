"""系统级检索配置解析服务（DB 覆盖 + Redis 缓存 + 内置兜底）。

逻辑仿 UserModelConfigService：
1. 查 Redis 缓存（key: retrieval_config:system，TTL 300s）
2. 缓存未命中 → 查 system_retrieval_config 单行
   - 无行 / 字段为 NULL → 回落内置默认值
3. 配置更新（save）后调用 invalidate_cache 清除缓存

模型类配置（embedding / reranker 的 model/base_url/api_key/dim）已收回 config.py
系统级维护（settings.MODEL_BASE_URL / EMBEDDING_* / RERANK_* / DASHSCOPE_API_KEY），
此处只保留检索策略键。
"""

from app.config import get_settings
from app.db.base import AsyncSessionLocal
from app.db.models import SystemRetrievalConfig
from app.db.repository import retrieval_config_repo
from app.utils.cache import cache_get_or_set, cache_delete

settings = get_settings()

# 数值/布尔字段：DB 非 NULL 时覆盖内置默认
_OVERRIDE_FIELDS = (
    "rerank_top_k", "similarity_threshold",
    "enable_query_rewrite", "enable_keyword_search", "enable_vector_search", "enable_rerank",
    "enable_graph_rag", "graph_search_mode",
)


class RetrievalConfigService:
    """解析系统级检索配置，返回生效配置字典。"""

    CACHE_KEY = "retrieval_config:system"
    CACHE_TTL = 300

    @staticmethod
    def _defaults() -> dict:
        """内置默认值。similarity_threshold 默认 0（不过滤，保持旧行为）。"""
        return {
            "rerank_top_k": settings.RAG_RERANK_TOP_K,
            "similarity_threshold": 0.0,
            "enable_query_rewrite": settings.RAG_ENABLE_QUERY_REWRITE,
            "enable_keyword_search": settings.RAG_ENABLE_KEYWORD_SEARCH,
            "enable_vector_search": settings.RAG_ENABLE_VECTOR_SEARCH,
            "enable_rerank": settings.RAG_ENABLE_RERANK,
            "enable_graph_rag": False,  # GraphRAG 图检索融合默认关闭（行为与旧版一致）
            "graph_search_mode": "auto",  # 图检索模式默认 local+global 并集
        }

    @classmethod
    async def resolve(cls) -> dict:
        """解析生效检索配置（内置默认 + DB 非空字段覆盖）。"""
        async def _fetch_from_db() -> dict:
            cfg = cls._defaults()
            async with AsyncSessionLocal() as session:
                row = await retrieval_config_repo.get_singleton(session)
            if row is None:
                return cfg
            for field in _OVERRIDE_FIELDS:
                value = getattr(row, field)
                if value is not None:
                    cfg[field] = value
            return cfg

        try:
            return await cache_get_or_set(
                cls.CACHE_KEY,
                _fetch_from_db,
                ttl=cls.CACHE_TTL,
                prefix="",
            ) or cls._defaults()
        except Exception as e:
            print(f"[RetrievalConfigService] resolve error: {e}")
            return cls._defaults()

    @classmethod
    async def invalidate_cache(cls) -> None:
        """配置更新后清除 Redis 缓存。"""
        try:
            await cache_delete(cls.CACHE_KEY, prefix="")
        except Exception as e:
            print(f"[RetrievalConfigService] invalidate cache error: {e}")

    @classmethod
    async def get_for_api(cls) -> dict:
        """返回给前端的配置（字段与 API 契约一致）。"""
        cfg = await cls.resolve()
        return {
            "rerank_top_k": cfg["rerank_top_k"],
            "similarity_threshold": cfg["similarity_threshold"],
            "enable_query_rewrite": cfg["enable_query_rewrite"],
            "enable_keyword_search": cfg["enable_keyword_search"],
            "enable_vector_search": cfg["enable_vector_search"],
            "enable_rerank": cfg["enable_rerank"],
            "enable_graph_rag": cfg["enable_graph_rag"],
            "graph_search_mode": cfg["graph_search_mode"],
        }

    @classmethod
    async def save(cls, data: dict) -> dict:
        """整体 upsert 配置（仅检索策略键；模型类配置在 config.py 系统级维护）。"""
        async with AsyncSessionLocal() as session:
            config = SystemRetrievalConfig(
                rerank_top_k=data["rerank_top_k"],
                similarity_threshold=data["similarity_threshold"],
                enable_query_rewrite=data["enable_query_rewrite"],
                enable_keyword_search=data["enable_keyword_search"],
                enable_vector_search=data["enable_vector_search"],
                enable_rerank=data["enable_rerank"],
                enable_graph_rag=bool(data.get("enable_graph_rag", False)),
                graph_search_mode=data.get("graph_search_mode") or "auto",
            )
            await retrieval_config_repo.upsert(session, config)
            await session.commit()

        await cls.invalidate_cache()
        return await cls.get_for_api()


retrieval_config_service = RetrievalConfigService()
