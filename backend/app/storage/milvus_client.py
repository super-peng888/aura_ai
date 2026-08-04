"""Milvus client: dense vector search over document chunks.

schema 保留 sparse_embedding 字段仅为兼容既有 collection 的列序（向量化已统一为
单一多模态模型，不再生成/检索 sparse 向量，写入时填空稀疏 {}）。
"""

import asyncio
from typing import Optional, Any
from pymilvus import (
    connections,
    FieldSchema,
    CollectionSchema,
    DataType,
    Collection,
    utility,
)

from app.config import get_settings

settings = get_settings()


class MilvusClient:
    """Milvus client for dense vector search."""

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
        # embedding 向量维度：懒解析（首次 ensure_collection 创建新 collection 时
        # 从 system_model_service 取生效 dimension，回落 settings.EMBEDDING_DIM）；
        # 已存在的 collection 以自身 schema 为准
        self.dim: Optional[int] = None
        self.collection: Optional[Collection] = None
        self._initialized = True

    @staticmethod
    def _resolve_dim() -> int:
        """取生效 embedding 维度（系统模型配置 DB 覆盖 settings）。

        本类为同步 API，而 resolve 为异步：在独立线程的新事件循环中执行，
        无论调用方是否处在事件循环内都安全；失败回落 settings.EMBEDDING_DIM。
        """
        try:
            import concurrent.futures

            from app.services.system_model_service import system_model_service

            def _run() -> dict:
                return asyncio.run(system_model_service.resolve("embedding"))

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                cfg = executor.submit(_run).result(timeout=15)
            return int(cfg.get("dimension") or settings.EMBEDDING_DIM)
        except Exception:
            return settings.EMBEDDING_DIM

    def connect(self):
        connections.connect(alias="default", host=settings.MILVUS_HOST, port=settings.MILVUS_PORT)

    def disconnect(self):
        connections.disconnect("default")

    def ensure_collection(self):
        if utility.has_collection(self.collection_name):
            self.collection = Collection(self.collection_name)
            return

        if not self.dim:
            self.dim = self._resolve_dim()
        if not self.dim:
            raise RuntimeError(
                "Embedding 维度未配置（系统模型配置 / settings.EMBEDDING_DIM），无法创建 Milvus collection"
            )

        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="document_id", dtype=DataType.VARCHAR, max_length=64),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.dim),
            # 兼容保留：不再生成/检索 sparse，写入时填空稀疏 {}
            FieldSchema(name="sparse_embedding", dtype=DataType.SPARSE_FLOAT_VECTOR),
            FieldSchema(name="metadata", dtype=DataType.JSON),
        ]

        schema = CollectionSchema(fields, description="Document chunks with dense vectors")
        self.collection = Collection(self.collection_name, schema)

        # Dense vector index (HNSW)
        dense_index = {
            "metric_type": "COSINE",
            "index_type": "HNSW",
            "params": {"M": 16, "efConstruction": 200},
        }
        self.collection.create_index("embedding", dense_index)

        # sparse 字段仍需索引才能 load collection（Milvus 要求向量字段必有索引）
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
        # 不在每次 insert 后强制 flush：flush 会封盖 segment 并同步阻塞（Windows 本地
        # 部署下可能长时间挂起，拖死索引 worker）。Milvus 会自行异步 flush，且 collection
        # load 后 growing segment 中的数据即可被检索，无需显式 flush 即可召回。
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
