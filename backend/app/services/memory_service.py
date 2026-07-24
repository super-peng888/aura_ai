"""Mem0 long-term memory service.

配置来源：
- llm：系统默认 DeepSeek（settings.DEEPSEEK_*，mem0 侧用 openai 兼容写法）
- embedder：系统级 embedding 配置（settings.MODEL_BASE_URL / EMBEDDING_TEXT_MODEL /
  EMBEDDING_DIM / DASHSCOPE_API_KEY）
- vector_store：settings 的 MEM0_VECTOR_STORE_*/QDRANT_*（基础设施，保留 env）

embedding 未配置（缺 DASHSCOPE_API_KEY）时 Mem0 初始化失败 = 明确 log 降级
（记忆能力关闭，不影响主链路）。client 在首次 async 调用（search/add）时懒建，
也可由 lifespan 调 init() 提前初始化。
"""

from typing import List, Optional

from app.config import get_settings

settings = get_settings


class MemoryService:
    """Wrapper around mem0ai.Memory for user/session memory."""

    _instance = None
    _client = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def _ensure_client(self):
        if self._client is not None:
            return self._client
        if not settings().ENABLE_MEM0:
            return None
        try:
            from mem0 import Memory

            if not settings().DASHSCOPE_API_KEY:
                raise RuntimeError("Embedding API Key 未配置（DASHSCOPE_API_KEY），Mem0 依赖 embedding")

            embedder_config = {
                "model": settings().EMBEDDING_TEXT_MODEL,
                "api_key": settings().DASHSCOPE_API_KEY,
            }
            if settings().MODEL_BASE_URL:
                embedder_config["openai_base_url"] = settings().MODEL_BASE_URL

            config = {
                "llm": {
                    "provider": "openai",  # openai 兼容协议，实际指向系统默认 DeepSeek
                    "config": {
                        "model": settings().DEEPSEEK_CHAT_MODEL,
                        "temperature": 0,
                        "api_key": settings().DEEPSEEK_API_KEY,
                        "openai_base_url": settings().DEEPSEEK_BASE_URL,
                    },
                },
                "embedder": {
                    "provider": "openai",
                    "config": embedder_config,
                },
                "vector_store": {
                    "provider": settings().MEM0_VECTOR_STORE_PROVIDER,
                    "config": {
                        "collection_name": settings().MEM0_COLLECTION_NAME,
                        "host": settings().QDRANT_HOST,
                        "port": settings().QDRANT_PORT,
                        "embedding_model_dims": settings().EMBEDDING_DIM,
                    },
                },
                "version": "v1.1",
            }
            self._client = Memory.from_config(config)
        except Exception as e:
            print(f"[MemoryService] Failed to init Mem0: {e}")
            self._client = None
        return self._client

    async def init(self) -> None:
        """在 lifespan 调用：提前初始化（失败仅告警降级，不阻塞启动）。"""
        await self._ensure_client()

    def is_ready(self) -> bool:
        return self._client is not None

    async def search(self, query: str, user_id: str, limit: int = 5) -> List[dict]:
        """Search relevant memories for a user."""
        client = await self._ensure_client()
        if client is None:
            return []
        try:
            results = client.search(query, user_id=user_id, limit=limit)
            return [{"memory": r.get("memory", ""), "score": r.get("score", 0)} for r in results]
        except Exception as e:
            print(f"[MemoryService] search error: {e}")
            return []

    async def add(self, content: str, user_id: str, metadata: Optional[dict] = None) -> None:
        """Add a memory for a user."""
        client = await self._ensure_client()
        if client is None:
            return
        try:
            client.add(content, user_id=user_id, metadata=metadata or {})
        except Exception as e:
            print(f"[MemoryService] add error: {e}")

# Global singleton
memory_service = MemoryService()
