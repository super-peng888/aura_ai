"""Tests for the in-process document indexer (app.services.indexer)."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.services import indexer


@pytest.mark.asyncio
class TestIndexDocument:
    async def test_index_document_returns_milvus_ids(self):
        """index_document 应 embed 后插入 Milvus 并返回字符串形式的 milvus_ids。"""
        chunks = [
            {"chunk_id": "c1", "content": "第一段", "page": 1, "image_ids": ["img-1"]},
            {"chunk_id": "c2", "content": "第二段", "page_number": 2},
        ]

        mock_embedding = MagicMock()
        mock_embedding.embed_dense = AsyncMock(return_value=[[0.1, 0.2], [0.3, 0.4]])
        mock_embedding.embed_sparse = AsyncMock(return_value=[{"a": 1.0}, {"b": 1.0}])

        mock_milvus = MagicMock()
        mock_milvus.insert_chunks = MagicMock(return_value=[101, 102])

        with patch("app.services.embedding_service.embedding_service", mock_embedding), \
             patch("app.storage.milvus_client.milvus_client", mock_milvus):
            milvus_ids = await indexer.index_document("doc-1", chunks)

        assert milvus_ids == ["101", "102"]
        mock_embedding.embed_dense.assert_awaited_once_with(["第一段", "第二段"])
        mock_embedding.embed_sparse.assert_awaited_once_with(["第一段", "第二段"])

        mock_milvus.insert_chunks.assert_called_once()
        kwargs = mock_milvus.insert_chunks.call_args.kwargs
        assert kwargs["chunk_ids"] == ["c1", "c2"]
        assert kwargs["document_ids"] == ["doc-1", "doc-1"]
        assert kwargs["contents"] == ["第一段", "第二段"]
        assert kwargs["embeddings"] == [[0.1, 0.2], [0.3, 0.4]]
        assert kwargs["sparse_embeddings"] == [{"a": 1.0}, {"b": 1.0}]
        assert kwargs["metadata_list"] == [
            {"page_number": 1, "chunk_index": 0, "image_ids": ["img-1"],
             "doc_title": "", "kb_id": "", "heading_path": "", "chunk_type": "text"},
            {"page_number": 2, "chunk_index": 1, "image_ids": [],
             "doc_title": "", "kb_id": "", "heading_path": "", "chunk_type": "text"},
        ]

    async def test_index_document_defaults_page_and_image_ids(self):
        """缺少 page/page_number 与 image_ids 时使用默认值。"""
        chunks = [{"chunk_id": "c1", "content": "内容"}]

        mock_embedding = MagicMock()
        mock_embedding.embed_dense = AsyncMock(return_value=[[0.1]])
        mock_embedding.embed_sparse = AsyncMock(return_value=[{}])

        mock_milvus = MagicMock()
        mock_milvus.insert_chunks = MagicMock(return_value=[1])

        with patch("app.services.embedding_service.embedding_service", mock_embedding), \
             patch("app.storage.milvus_client.milvus_client", mock_milvus):
            await indexer.index_document("doc-1", chunks)

        metadata = mock_milvus.insert_chunks.call_args.kwargs["metadata_list"]
        assert metadata == [{"page_number": 1, "chunk_index": 0, "image_ids": [],
                             "doc_title": "", "kb_id": "", "heading_path": "", "chunk_type": "text"}]


@pytest.mark.asyncio
class TestDeleteDocument:
    async def test_delete_document_calls_delete_by_document(self):
        """delete_document 应调用 milvus_client.delete_by_document。"""
        mock_milvus = MagicMock()

        with patch("app.storage.milvus_client.milvus_client", mock_milvus):
            await indexer.delete_document("doc-1")

        mock_milvus.delete_by_document.assert_called_once_with("doc-1")
