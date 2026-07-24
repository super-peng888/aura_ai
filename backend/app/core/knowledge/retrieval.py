"""Multi-route retrieval via Milvus hybrid search (dense semantic + sparse lexical)."""

from typing import List, Optional

from app.config import get_settings
from app.storage.milvus_client import milvus_client
from app.services.embedding_service import embedding_service

settings = get_settings()


class RetrievalService:
    """Retrieval using Milvus hybrid search — no PG keyword search needed."""

    def __init__(self):
        self.enable_keyword = settings.RAG_ENABLE_KEYWORD_SEARCH
        self.enable_vector = settings.RAG_ENABLE_VECTOR_SEARCH
        self.enable_hybrid = settings.MILVUS_ENABLE_HYBRID

    async def retrieve(
        self,
        query: str,
        query_embedding: Optional[List[float]] = None,
        query_sparse: Optional[dict] = None,
        document_ids: Optional[List[str]] = None,
        knowledge_base_ids: Optional[List[str]] = None,
        top_k: int = 20,
        filters: Optional[dict] = None,
        enable_keyword: Optional[bool] = None,
        enable_vector: Optional[bool] = None,
    ) -> List[dict]:
        """Retrieve chunks using Milvus hybrid search.

        enable_keyword / enable_vector 为 None 时回落 __init__ 的 .env 快照。
        document_ids / knowledge_base_ids / filters 由 _apply_filters 编译为
        Milvus filter 表达式下推到检索，无过滤条件时走原路径。

        Returns list of dicts with chunk_id, document_id, content, score, search_type, image_ids.
        """
        enable_keyword = self.enable_keyword if enable_keyword is None else enable_keyword
        enable_vector = self.enable_vector if enable_vector is None else enable_vector

        if not enable_vector and not enable_keyword:
            return []

        # Generate embeddings if not provided
        if query_embedding is None:
            query_embedding = await embedding_service.embed_query(query)
        if query_sparse is None and self.enable_hybrid and enable_keyword:
            query_sparse = await embedding_service.embed_query_sparse(query)

        filter_expr = self._apply_filters(
            document_ids=document_ids,
            knowledge_base_ids=knowledge_base_ids,
            filters=filters,
        )

        # Route decision
        if self.enable_hybrid and enable_keyword and enable_vector and query_sparse:
            hits = milvus_client.hybrid_search(
                dense_embedding=query_embedding,
                sparse_embedding=query_sparse,
                top_k=top_k,
                filters=filter_expr,
            )
            search_type_label = "hybrid"
        elif enable_vector:
            hits = milvus_client.search(
                query_embedding=query_embedding,
                top_k=top_k,
                filters=filter_expr,
            )
            search_type_label = "vector"
        elif enable_keyword and query_sparse:
            hits = milvus_client.search_sparse(
                sparse_embedding=query_sparse,
                top_k=top_k,
                filters=filter_expr,
            )
            search_type_label = "keyword"
        else:
            return []

        results = []
        for hit in hits:
            meta = hit.get("metadata") or {}
            results.append({
                "chunk_id": hit["chunk_id"],
                "document_id": hit["document_id"],
                "content": hit.get("content", ""),
                "page_number": meta.get("page_number"),
                "score": float(hit["score"]),
                "search_type": search_type_label,
                "image_ids": meta.get("image_ids", []),
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
