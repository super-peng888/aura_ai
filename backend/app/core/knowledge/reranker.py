"""Re-ranking service for improving retrieval precision.

单一实现：通用 HTTP rerank 端点（Cohere / Jina / SiliconFlow 等主流 rerank API
通用形状），base_url 即完整 rerank 端点（不做任何路径拼接，避免
多余拼 /rerank 导致地址错误），POST body {model, query, documents, top_n}，
解析返回 results: [{index, relevance_score}] 重排 chunks。

运行配置经 system_model_service.resolve("rerank") 解析（DB 覆盖 settings 默认，
api_key 回落 DASHSCOPE_API_KEY），保存后运行时生效。model / base_url / api_key
未配置时按"不重排、按现有 score 截断"降级并记 warning——rerank 是增强项而非必需项，
配置缺失不该阻断问答主链路（与 embedding 的 RuntimeError 语义不同）。
"""

import logging
from typing import List

import httpx

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class RerankerService:
    """Re-rank retrieved chunks via a generic HTTP rerank endpoint."""

    def __init__(self):
        self.top_k = settings.RAG_RERANK_TOP_K
        # httpx.AsyncClient 懒加载构建一次；Authorization 头按次请求构建
        # （key 可在模型配置页热更，不能缓存在 client 上）
        self._client: httpx.AsyncClient = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    @staticmethod
    def _truncate_by_score(chunks: List[dict], top_k: int) -> List[dict]:
        """No reranking, just return top_k by existing score."""
        return sorted(chunks, key=lambda x: x.get("score", 0), reverse=True)[:top_k]

    async def rerank(
        self,
        query: str,
        chunks: List[dict],
        top_k: int = None,
    ) -> List[dict]:
        """Re-rank chunks by relevance to the query.

        Args:
            query: User query
            chunks: List of chunk dicts with 'content' field
            top_k: Number of top results to return

        Returns:
            Re-ranked and truncated list of chunks

        降级路径（均按原 score 截断，不阻断问答）：
        - model / base_url / api_key 未配置 → warning 降级
        - HTTP 调用失败 / 返回空 results → warning 降级
        """
        if not chunks:
            return []

        top_k = top_k or self.top_k

        from app.services.system_model_service import system_model_service

        cfg = await system_model_service.resolve("rerank")
        model = cfg.get("model") or ""
        base_url = cfg.get("base_url") or ""
        api_key = cfg.get("api_key") or ""
        if not model or not base_url or not api_key:
            # rerank 是增强项：配置缺失时降级而非报错，不阻断检索主链路
            logger.warning("Rerank 未配置（model/base_url/api_key），按原 score 截断降级")
            return self._truncate_by_score(chunks, top_k)

        client = self._get_client()
        documents = [chunk["content"] for chunk in chunks]

        try:
            # base_url 即完整端点，直接请求，不再自动拼接 /rerank
            response = await client.post(
                base_url.rstrip("/"),
                json={"model": model, "query": query, "documents": documents, "top_n": top_k},
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
            results = (response.json() or {}).get("results") or []
        except Exception as e:
            # rerank 失败不该让问答失败：按原 score 截断降级
            logger.warning("HTTP rerank request failed: %s, falling back to score-based ranking", e)
            return self._truncate_by_score(chunks, top_k)

        if not results:
            logger.warning("HTTP rerank returned empty results, falling back to score-based ranking")
            return self._truncate_by_score(chunks, top_k)

        # 按 rerank 结果重排 chunks
        reranked = []
        for item in results:
            index = item.get("index")
            if index is None or not (0 <= index < len(chunks)):
                continue
            chunk = chunks[index].copy()
            chunk["score"] = item.get("relevance_score", 0.0)
            # 标记已经 rerank 重打分：similarity_threshold 只对 rerank 分数（0~1 量纲）
            # 生效；降级/关闭 rerank 时的 RRF 融合分（~0.016）与阈值不可比，不该被误杀
            chunk["reranked"] = True
            # 不覆写已有 search_type（graph/graph_global 结果需保留来源标记，
            # 供 rag_pipeline 的 similarity_threshold 豁免判断）
            chunk.setdefault("search_type", "rerank")
            reranked.append(chunk)

        return reranked[:top_k]


# Global singleton
reranker_service = RerankerService()
