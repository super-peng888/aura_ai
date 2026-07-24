"""Milvus client with hybrid search: dense vector + sparse vector + full text in metadata."""

import asyncio
from typing import Optional, Any
from pymilvus import (
    connections,
    FieldSchema,
    CollectionSchema,
    DataType,
    Collection,
    utility,
    AnnSearchRequest,
    RRFRanker,
)

from app.config import get_settings

settings = get_settings()


class MilvusClient:
    """Milvus client supporting dense + sparse hybrid search."""

    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.collection_name = settings.MILVUS_COLLECTION
        # embedding 向量维度：系统级 settings.EMBEDDING_DIM，
        # 仅在创建新 collection 时使用；已存在的 collection 以自身 schema 为准
        self.dim: Optional[int] = settings.EMBEDDING_DIM
        self.enable_hybrid = settings.MILVUS_ENABLE_HYBRID
        self.collection: Optional[Collection] = None
        self._initialized = True

    def connect(self):
        connections.connect(alias="default", host=settings.MILVUS_HOST, port=settings.MILVUS_PORT)

    def disconnect(self):
        connections.disconnect("default")

    def ensure_collection(self):
        if utility.has_collection(self.collection_name):
            self.collection = Collection(self.collection_name)
            return

        if not self.dim:
            raise RuntimeError(
                "Embedding 维度未配置（settings.EMBEDDING_DIM），无法创建 Milvus collection"
            )

        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="document_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.dim),
            FieldSchema(name="sparse_embedding", dtype=DataType.SPARSE_FLOAT_VECTOR),
            FieldSchema(name="metadata", dtype=DataType.JSON),
        ]

        schema = CollectionSchema(fields, description="Document chunks with dense + sparse vectors")
        self.collection = Collection(self.collection_name, schema)

        # Dense vector index (HNSW)
        dense_index = {
            "metric_type": "COSINE",
            "index_type": "HNSW",
            "params": {"M": 16, "efConstruction": 200},
        }
        self.collection.create_index("embedding", dense_index)

        # Sparse vector index
        if self.enable_hybrid:
            sparse_index = {
                "metric_type": "IP",
                "index_type": "SPARSE_INVERTED_INDEX",
                "params": {"drop_ratio_build": 0.2},
            }
            self.collection.create_index("sparse_embedding", sparse_index)

        self.collection.load()

    def init(self):
        self.connect()
        self.ensure_collection()

    def insert_chunks(
        self,
        chunk_ids: list[str],
        document_ids: list[str],
        contents: list[str],
        embeddings: list[list[float]],
        sparse_embeddings: Optional[list[dict]],
        metadata_list: list[dict],
    ) -> list[int]:
        if not self.collection:
            self.init()

        entities = [
            chunk_ids,
            document_ids,
            contents,
            embeddings,
            sparse_embeddings or [{}] * len(chunk_ids),
            metadata_list,
        ]

        result = self.collection.insert(entities)
        self.collection.flush()
        return result.primary_keys

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        document_ids: Optional[list[str]] = None,
        filters: Optional[str] = None,
        ef: int = 128,
    ) -> list[dict]:
        """Dense vector search only."""
        if not self.collection:
            self.init()

        search_params = {"metric_type": "COSINE", "params": {"ef": ef}}
        expr_parts = []
        if document_ids:
            doc_ids_str = ", ".join([f'"{d}"' for d in document_ids])
            expr_parts.append(f"document_id in [{doc_ids_str}]")
        if filters:
            expr_parts.append(filters)

        expr = " and ".join(expr_parts) if expr_parts else None

        results = self.collection.search(
            data=[query_embedding],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            expr=expr,
            output_fields=["chunk_id", "document_id", "content", "metadata"],
        )

        hits = []
        for result in results:
            for hit in result:
                hits.append({
                    "id": hit.id,
                    "chunk_id": hit.entity.get("chunk_id"),
                    "document_id": hit.entity.get("document_id"),
                    "content": hit.entity.get("content"),
                    "score": hit.distance,
                    "metadata": hit.entity.get("metadata"),
                })
        return hits

    def search_sparse(
        self,
        sparse_embedding: dict,
        top_k: int = 10,
        document_ids: Optional[list[str]] = None,
        filters: Optional[str] = None,
    ) -> list[dict]:
        """Sparse vector search (keyword/BM25-like)."""
        if not self.collection or not self.enable_hybrid:
            return []

        expr_parts = []
        if document_ids:
            doc_ids_str = ", ".join([f'"{d}"' for d in document_ids])
            expr_parts.append(f"document_id in [{doc_ids_str}]")
        if filters:
            expr_parts.append(filters)
        expr = " and ".join(expr_parts) if expr_parts else None

        search_params = {"metric_type": "IP", "params": {"drop_ratio_build": 0.2}}

        results = self.collection.search(
            data=[sparse_embedding],
            anns_field="sparse_embedding",
            param=search_params,
            limit=top_k,
            expr=expr,
            output_fields=["chunk_id", "document_id", "content", "metadata"],
        )

        hits = []
        for result in results:
            for hit in result:
                hits.append({
                    "id": hit.id,
                    "chunk_id": hit.entity.get("chunk_id"),
                    "document_id": hit.entity.get("document_id"),
                    "content": hit.entity.get("content"),
                    "score": hit.distance,
                    "metadata": hit.entity.get("metadata"),
                })
        return hits

    def hybrid_search(
        self,
        dense_embedding: list[float],
        sparse_embedding: dict,
        top_k: int = 10,
        document_ids: Optional[list[str]] = None,
        filters: Optional[str] = None,
    ) -> list[dict]:
        """Hybrid search: dense semantic + sparse lexical with RRF reranking."""
        if not self.collection:
            self.init()

        if not self.enable_hybrid or not sparse_embedding:
            return self.search(dense_embedding, top_k=top_k, document_ids=document_ids, filters=filters)

        expr_parts = []
        if document_ids:
            doc_ids_str = ", ".join([f'"{d}"' for d in document_ids])
            expr_parts.append(f"document_id in [{doc_ids_str}]")
        if filters:
            expr_parts.append(filters)
        expr = " and ".join(expr_parts) if expr_parts else None

        dense_req = AnnSearchRequest(
            data=[dense_embedding],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"ef": 128}},
            limit=top_k * 2,
            expr=expr,
        )

        sparse_req = AnnSearchRequest(
            data=[sparse_embedding],
            anns_field="sparse_embedding",
            param={"metric_type": "IP", "params": {"drop_ratio_build": 0.2}},
            limit=top_k * 2,
            expr=expr,
        )

        results = self.collection.hybrid_search(
            reqs=[dense_req, sparse_req],
            rerank=RRFRanker(k=60),
            limit=top_k,
            output_fields=["chunk_id", "document_id", "content", "metadata"],
        )

        hits = []
        for result in results:
            for hit in result:
                hits.append({
                    "id": hit.id,
                    "chunk_id": hit.entity.get("chunk_id"),
                    "document_id": hit.entity.get("document_id"),
                    "content": hit.entity.get("content"),
                    "score": hit.distance,
                    "metadata": hit.entity.get("metadata"),
                })
        return hits

    def delete_by_document(self, document_id: str):
        if not self.collection:
            self.init()
        self.collection.delete(f'document_id == "{document_id}"')

    def delete_by_chunk_ids(self, chunk_ids: list[str]):
        if not self.collection:
            self.init()
        if not chunk_ids:
            return
        ids_str = ", ".join([f'"{c}"' for c in chunk_ids])
        self.collection.delete(f"chunk_id in [{ids_str}]")


milvus_client = MilvusClient()
