"""Vector retrieval via Milvus dense semantic search."""

from typing import List, Optional

from app.config import get_settings
from app.storage.milvus_client import milvus_client
from app.services.embedding_service import embedding_service

settings = get_settings()


class RetrievalService:
    """Retrieval using Milvus dense vector search."""

    def __init__(self):
        self.enable_keyword = settings.RAG_ENABLE_KEYWORD_SEARCH
        self.enable_vector = settings.RAG_ENABLE_VECTOR_SEARCH

    async def retrieve(
        self,
        query: str,
        query_embedding: Optional[List[float]] = None,
        document_ids: Optional[List[str]] = None,
        knowledge_base_ids: Optional[List[str]] = None,
        top_k: int = 20,
        filters: Optional[dict] = None,
        enable_keyword: Optional[bool] = None,
        enable_vector: Optional[bool] = None,
    ) -> List[dict]:
        """Retrieve chunks using Milvus dense vector search.

        向量化已统一为单一多模态模型（无 sparse 向量），关键词召回由向量
        语义检索覆盖：enable_keyword / enable_vector 任一开启即走向量检索，
        两者都关时返回空（None 时回落 __init__ 的 .env 快照）。
        document_ids / knowledge_base_ids / filters 由 _apply_filters 编译为
        Milvus filter 表达式下推到检索，无过滤条件时走原路径。

        Returns list of dicts with chunk_id, document_id, content, score, search_type, image_ids.
        """
        enable_keyword = self.enable_keyword if enable_keyword is None else enable_keyword
        enable_vector = self.enable_vector if enable_vector is None else enable_vector

        if not enable_vector and not enable_keyword:
            return []

        # Generate embedding if not provided
        if query_embedding is None:
            query_embedding = await embedding_service.embed_query(query)

        filter_expr = self._apply_filters(
            document_ids=document_ids,
            knowledge_base_ids=knowledge_base_ids,
            filters=filters,
        )

        hits = milvus_client.search(
            query_embedding=query_embedding,
            top_k=top_k,
            filters=filter_expr,
        )

        results = []
        for hit in hits:
            meta = hit.get("metadata") or {}
            results.append({
                "chunk_id": hit["chunk_id"],
                "document_id": hit["document_id"],
                "content": hit.get("content", ""),
                "page_number": meta.get("page_number"),
                "score": float(hit["score"]),
                "search_type": "vector",
                "image_ids": meta.get("image_ids", []),
                # 父子分块：命中子块，检索后回捞父节完整内容送 LLM
                "parent_id": meta.get("parent_id"),
                "parent_content": meta.get("parent_content"),
            })

        return results

    @staticmethod
    def _escape(value) -> str:
        """转义 Milvus 表达式字符串值中的特殊字符。"""
        return str(value).replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    def _apply_filters(
        document_ids: Optional[List[str]] = None,
        knowledge_base_ids: Optional[List[str]] = None,
        filters: Optional[dict] = None,
    ) -> Optional[str]:
        """将过滤条件编译为 Milvus filter 表达式；无条件时返回 None。

        规则：
        - document_ids:        document_id in ["a", "b"]
        - knowledge_base_ids:  metadata["kb_id"] in ["a", "b"]
        - filters dict:        标量值 -> metadata["key"] == "value"
                               列表值 -> metadata["key"] in [...]
        多条件以 " and " 连接。
        """
        parts = []
        if document_ids:
            ids = ", ".join(f'"{RetrievalService._escape(d)}"' for d in document_ids)
            parts.append(f"document_id in [{ids}]")
        if knowledge_base_ids:
            ids = ", ".join(f'"{RetrievalService._escape(k)}"' for k in knowledge_base_ids)
            parts.append(f'metadata["kb_id"] in [{ids}]')
        if filters:
            for key, value in filters.items():
                if value is None or value == "":
                    continue
                if isinstance(value, (list, tuple, set)):
                    vals = ", ".join(f'"{RetrievalService._escape(v)}"' for v in value)
                    parts.append(f'metadata["{key}"] in [{vals}]')
                else:
                    parts.append(f'metadata["{key}"] == "{RetrievalService._escape(value)}"')
        return " and ".join(parts) if parts else None


retrieval_service = RetrievalService()
