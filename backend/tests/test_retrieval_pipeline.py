"""Tests for the retrieval pipeline refactor: indexer metadata, filter expr,
structured chunking (heading/table), and the reindex script."""

import importlib.util
from pathlib import Path

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.services import indexer
from app.core.knowledge.retrieval import RetrievalService
from app.services.document_parser import (
    ParsedPage,
    ParseStrategyConfig,
    split_pages_to_chunks,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent
REINDEX_SCRIPT = BACKEND_DIR / "scripts" / "reindex_documents.py"


def _mock_embedding():
    mock = MagicMock()
    mock.embed_dense = AsyncMock(return_value=[[0.1, 0.2]])
    mock.embed_sparse = AsyncMock(return_value=[{"a": 1.0}])
    return mock


@pytest.mark.asyncio
class TestIndexerMetadata:
    async def test_new_metadata_fields_written(self):
        """index_document 应把 doc_title/kb_id/heading_path/chunk_type 写入 metadata。"""
        chunks = [
            {"chunk_id": "c1", "content": "正文", "page": 1,
             "image_ids": [], "heading": "第一章 > 1.1 节", "chunk_type": "text"},
            {"chunk_id": "c2", "content": "| a |\n| - |\n| 1 |", "page": 1,
             "heading": "第一章", "chunk_type": "table"},
        ]
        mock_embedding = _mock_embedding()
        mock_embedding.embed_dense = AsyncMock(return_value=[[0.1], [0.2]])
        mock_embedding.embed_sparse = AsyncMock(return_value=[{}, {}])

        mock_milvus = MagicMock()
        mock_milvus.insert_chunks = MagicMock(return_value=[11, 12])

        with patch("app.services.embedding_service.embedding_service", mock_embedding), \
             patch("app.storage.milvus_client.milvus_client", mock_milvus):
            milvus_ids = await indexer.index_document(
                "doc-1", chunks, doc_title="年度报告.pdf", kb_id="kb-9",
            )

        assert milvus_ids == ["11", "12"]
        metadata = mock_milvus.insert_chunks.call_args.kwargs["metadata_list"]
        assert metadata[0]["doc_title"] == "年度报告.pdf"
        assert metadata[0]["kb_id"] == "kb-9"
        assert metadata[0]["heading_path"] == "第一章 > 1.1 节"
        assert metadata[0]["chunk_type"] == "text"
        assert metadata[1]["heading_path"] == "第一章"
        assert metadata[1]["chunk_type"] == "table"

    async def test_metadata_defaults_when_fields_missing(self):
        """chunk 缺少 heading/chunk_type、未传 doc_title/kb_id 时使用默认值。"""
        chunks = [{"chunk_id": "c1", "content": "内容"}]
        mock_milvus = MagicMock()
        mock_milvus.insert_chunks = MagicMock(return_value=[1])

        with patch("app.services.embedding_service.embedding_service", _mock_embedding()), \
             patch("app.storage.milvus_client.milvus_client", mock_milvus):
            await indexer.index_document("doc-1", chunks)

        metadata = mock_milvus.insert_chunks.call_args.kwargs["metadata_list"][0]
        assert metadata["doc_title"] == ""
        assert metadata["kb_id"] == ""
        assert metadata["heading_path"] == ""
        assert metadata["chunk_type"] == "text"


class TestApplyFilters:
    def test_no_filters_returns_none(self):
        assert RetrievalService._apply_filters() is None
        assert RetrievalService._apply_filters(document_ids=[], filters={}) is None
        assert RetrievalService._apply_filters(filters={"doc_title": ""}) is None

    def test_document_ids(self):
        expr = RetrievalService._apply_filters(document_ids=["d1", "d2"])
        assert expr == 'document_id in ["d1", "d2"]'

    def test_knowledge_base_ids(self):
        expr = RetrievalService._apply_filters(knowledge_base_ids=["kb1"])
        assert expr == 'metadata["kb_id"] in ["kb1"]'

    def test_filters_scalar_equality(self):
        expr = RetrievalService._apply_filters(filters={"doc_title": "年度报告"})
        assert expr == 'metadata["doc_title"] == "年度报告"'

    def test_filters_list_value(self):
        expr = RetrievalService._apply_filters(filters={"kb_id": ["a", "b"]})
        assert expr == 'metadata["kb_id"] in ["a", "b"]'

    def test_combined(self):
        expr = RetrievalService._apply_filters(
            document_ids=["d1"],
            knowledge_base_ids=["kb1", "kb2"],
            filters={"doc_title": "报告"},
        )
        assert expr == (
            'document_id in ["d1"]'
            ' and metadata["kb_id"] in ["kb1", "kb2"]'
            ' and metadata["doc_title"] == "报告"'
        )

    def test_value_escaping(self):
        expr = RetrievalService._apply_filters(filters={"doc_title": 'a"b'})
        assert expr == 'metadata["doc_title"] == "a\\"b"'


class TestSplitPagesToChunks:
    def _strategy(self, split_method="sentence"):
        return ParseStrategyConfig(chunk_size=800, chunk_overlap=100, split_method=split_method)

    def test_plain_page_no_heading(self):
        """无标题的页面：heading 为空串，chunk_type 为 text，既有字段不变。"""
        pages = [ParsedPage(page_number=1, text="这是一段正文内容。")]
        chunks = split_pages_to_chunks(pages, self._strategy(), "doc1")

        assert len(chunks) == 1
        c = chunks[0]
        assert c["chunk_id"] == "doc1_chunk_0000"
        assert c["doc_id"] == "doc1"
        assert c["page"] == 1
        assert c["content"] == "这是一段正文内容。"
        assert c["image_ids"] == []
        assert c["heading"] == ""
        assert c["chunk_type"] == "text"

    def test_heading_attached_to_chunk(self):
        pages = [ParsedPage(
            page_number=1,
            text="第一章 概述\n\n这是正文内容。",
            headings=[{"text": "第一章 概述", "level": 1, "pos": 0}],
        )]
        chunks = split_pages_to_chunks(pages, self._strategy(), "doc1")

        assert chunks[0]["heading"] == "第一章 概述"
        assert chunks[0]["chunk_type"] == "text"

    def test_heading_path_across_pages(self):
        """跨页维护标题层级栈：第二页的二级标题拼出一级路径。"""
        pages = [
            ParsedPage(page_number=1, text="第一章 总纲\n\n总纲正文。",
                       headings=[{"text": "第一章 总纲", "level": 1, "pos": 0}]),
            ParsedPage(page_number=2, text="1.2 节 细则\n\n细则正文。",
                       headings=[{"text": "1.2 节 细则", "level": 2, "pos": 0}]),
        ]
        chunks = split_pages_to_chunks(pages, self._strategy(), "doc1")

        assert chunks[0]["heading"] == "第一章 总纲"
        assert chunks[1]["heading"] == "第一章 总纲 > 1.2 节 细则"

    def test_table_becomes_independent_chunk(self):
        table_md = "| 列A | 列B |\n| --- | --- |\n| 1 | 2 |"
        pages = [ParsedPage(
            page_number=3,
            text="第二章 数据\n\n见下表。",
            tables=[table_md],
            headings=[{"text": "第二章 数据", "level": 1, "pos": 0}],
        )]
        chunks = split_pages_to_chunks(pages, self._strategy(), "doc1")

        assert len(chunks) == 2
        table_chunk = chunks[1]
        assert table_chunk["chunk_type"] == "table"
        assert table_chunk["page"] == 3
        assert table_md in table_chunk["content"]
        # 表格 chunk 含表头上下文
        assert table_chunk["content"].startswith("第二章 数据")
        assert table_chunk["heading"] == "第二章 数据"
        # chunk_id 顺序连续
        assert table_chunk["chunk_id"] == "doc1_chunk_0001"

    def test_structured_split_prefers_real_headings(self):
        """structured 模式优先用提取到的真实标题切分。"""
        text = "引言部分。\n\n第一章 概述\n\n概述正文。\n\n第二章 详述\n\n详述正文。"
        pages = [ParsedPage(
            page_number=1,
            text=text,
            headings=[
                {"text": "第一章 概述", "level": 1, "pos": text.index("第一章 概述")},
                {"text": "第二章 详述", "level": 1, "pos": text.index("第二章 详述")},
            ],
        )]
        chunks = split_pages_to_chunks(pages, self._strategy("structured"), "doc1")

        assert len(chunks) == 3
        assert chunks[0]["heading"] == ""
        assert chunks[1]["heading"] == "第一章 概述"
        assert "概述正文" in chunks[1]["content"]
        assert chunks[2]["heading"] == "第二章 详述"


class TestReindexScript:
    def _load_module(self):
        spec = importlib.util.spec_from_file_location("reindex_documents", str(REINDEX_SCRIPT))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_script_importable(self):
        module = self._load_module()
        assert callable(module.parse_args)
        assert callable(module.main)
        assert callable(module.run)
        assert callable(module.reindex_document)

    def test_parse_args_all(self):
        module = self._load_module()
        args = module.parse_args(["--all"])
        assert args.all is True
        assert args.doc_ids is None

    def test_parse_args_doc_ids(self):
        module = self._load_module()
        args = module.parse_args(["--doc-id", "a", "--doc-id", "b"])
        assert args.all is False
        assert args.doc_ids == ["a", "b"]

    def test_parse_args_requires_choice(self):
        module = self._load_module()
        with pytest.raises(SystemExit):
            module.parse_args([])

    def test_parse_args_mutually_exclusive(self):
        module = self._load_module()
        with pytest.raises(SystemExit):
            module.parse_args(["--all", "--doc-id", "a"])
