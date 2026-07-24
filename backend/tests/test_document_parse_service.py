"""Tests for app.services.document_parse_service 的 PG 落库语义。

覆盖统一后的 update_chunk_milvus_ids（按 chunk_id 映射 + 自包含 commit）、
save_parse_metadata 的自包含 commit，以及 index_document_sync 同步路径的落库断言。
"""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services import document_parse_service as dps


class _SessionCtx:
    """模拟 AsyncSessionLocal() 返回的 async context manager。"""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


def _make_session():
    session = MagicMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


def _patch_session_factory(monkeypatch, session):
    factory = MagicMock(return_value=_SessionCtx(session))
    monkeypatch.setattr(dps, "AsyncSessionLocal", factory)
    return factory


def _db_chunk(chunk_index, milvus_id="pending"):
    return SimpleNamespace(chunk_index=chunk_index, milvus_id=milvus_id)


def _payload(doc_id, idx, **overrides):
    payload = {
        "chunk_id": f"{doc_id}_chunk_{idx:04d}",
        "doc_id": doc_id,
        "page": 1,
        "content": f"内容{idx}",
        "image_ids": [],
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
class TestUpdateChunkMilvusIds:
    async def test_maps_by_chunk_id_when_chunks_out_of_order(self, monkeypatch):
        """chunks 列表乱序时按 chunk_id 映射，milvus_id 不错位。"""
        session = _make_session()
        _patch_session_factory(monkeypatch, session)
        db_chunks = [_db_chunk(0), _db_chunk(1), _db_chunk(2)]
        monkeypatch.setattr(
            dps.chunk_repo, "list_by_document", AsyncMock(return_value=db_chunks)
        )

        # indexer 返回的 milvus_ids 与 chunks 顺序对齐，此处 chunks 乱序传入
        chunks = [_payload("doc-1", 2), _payload("doc-1", 0), _payload("doc-1", 1)]
        milvus_ids = ["m2", "m0", "m1"]
        await dps.update_chunk_milvus_ids("doc-1", chunks, milvus_ids)

        assert db_chunks[0].milvus_id == "m0"
        assert db_chunks[1].milvus_id == "m1"
        assert db_chunks[2].milvus_id == "m2"
        session.commit.assert_awaited_once()
        session.add.assert_not_called()

    async def test_maps_by_explicit_chunk_index_field(self, monkeypatch):
        """无标准 chunk_id 后缀时按显式 chunk_index 字段映射。"""
        session = _make_session()
        _patch_session_factory(monkeypatch, session)
        db_chunks = [_db_chunk(0), _db_chunk(1)]
        monkeypatch.setattr(
            dps.chunk_repo, "list_by_document", AsyncMock(return_value=db_chunks)
        )

        chunks = [
            {"chunk_id": "c2", "content": "第二段", "chunk_index": 1},
            {"chunk_id": "c1", "content": "第一段", "chunk_index": 0},
        ]
        await dps.update_chunk_milvus_ids("doc-1", chunks, ["mB", "mA"])

        assert db_chunks[0].milvus_id == "mA"
        assert db_chunks[1].milvus_id == "mB"
        session.commit.assert_awaited_once()

    async def test_commit_called(self, monkeypatch):
        """更新后显式 commit（sync 路径落库依赖于此）。"""
        session = _make_session()
        _patch_session_factory(monkeypatch, session)
        db_chunks = [_db_chunk(0)]
        monkeypatch.setattr(
            dps.chunk_repo, "list_by_document", AsyncMock(return_value=db_chunks)
        )

        await dps.update_chunk_milvus_ids("doc-1", [_payload("doc-1", 0)], ["m0"])

        assert db_chunks[0].milvus_id == "m0"
        session.commit.assert_awaited_once()

    async def test_empty_inputs_are_noop(self, monkeypatch):
        """空 chunks 或空 milvus_ids 时不建 session、不查库、不 commit。"""
        session = _make_session()
        factory = _patch_session_factory(monkeypatch, session)
        list_mock = AsyncMock(return_value=[_db_chunk(0)])
        monkeypatch.setattr(dps.chunk_repo, "list_by_document", list_mock)

        await dps.update_chunk_milvus_ids("doc-1", [], ["m0"])
        await dps.update_chunk_milvus_ids("doc-1", [_payload("doc-1", 0)], [])
        await dps.update_chunk_milvus_ids("doc-1", [], [])

        factory.assert_not_called()
        list_mock.assert_not_awaited()
        session.commit.assert_not_awaited()

    async def test_length_mismatch_truncates_to_shorter(self, monkeypatch):
        """chunks 与 milvus_ids 长度不一致时按较短者对齐，仍正常 commit。"""
        session = _make_session()
        _patch_session_factory(monkeypatch, session)
        db_chunks = [_db_chunk(0), _db_chunk(1), _db_chunk(2)]
        monkeypatch.setattr(
            dps.chunk_repo, "list_by_document", AsyncMock(return_value=db_chunks)
        )

        chunks = [_payload("doc-1", i) for i in range(3)]
        await dps.update_chunk_milvus_ids("doc-1", chunks, ["m0", "m1"])

        assert db_chunks[0].milvus_id == "m0"
        assert db_chunks[1].milvus_id == "m1"
        assert db_chunks[2].milvus_id == "pending"
        session.commit.assert_awaited_once()

    async def test_creates_chunk_record_when_missing(self, monkeypatch):
        """PG 无匹配记录时兜底新建 DocumentChunk。"""
        session = _make_session()
        _patch_session_factory(monkeypatch, session)
        db_chunks = [_db_chunk(0)]
        monkeypatch.setattr(
            dps.chunk_repo, "list_by_document", AsyncMock(return_value=db_chunks)
        )

        chunks = [_payload("doc-1", 0), _payload("doc-1", 1)]
        await dps.update_chunk_milvus_ids("doc-1", chunks, ["m0", "m1"])

        assert db_chunks[0].milvus_id == "m0"
        session.add.assert_called_once()
        created = session.add.call_args.args[0]
        assert created.document_id == "doc-1"
        assert created.milvus_id == "m1"
        assert created.chunk_index == 1
        assert created.content == "内容1"
        session.commit.assert_awaited_once()


@pytest.mark.asyncio
class TestSaveParseMetadata:
    async def test_commits_chunk_and_image_metadata(self, monkeypatch):
        """save_parse_metadata 自包含 session 并显式 commit。"""
        session = _make_session()
        _patch_session_factory(monkeypatch, session)
        chunk_create = AsyncMock()
        image_create = AsyncMock()
        monkeypatch.setattr(dps.chunk_repo, "create", chunk_create)
        monkeypatch.setattr(dps.image_repo, "create", image_create)

        chunks = [_payload("doc-1", 0), _payload("doc-1", 1)]
        images = [{"image_id": "img-1", "oss_url": "http://x/img.png", "page_number": 1}]
        await dps.save_parse_metadata("doc-1", chunks, images, MagicMock())

        assert chunk_create.await_count == 2
        assert image_create.await_count == 1
        # chunk 记录以 pending 占位，等待索引后回填 milvus_id
        first_chunk = chunk_create.call_args_list[0].args[1]
        assert first_chunk.document_id == "doc-1"
        assert first_chunk.milvus_id == "pending"
        assert first_chunk.chunk_index == 0
        session.commit.assert_awaited_once()


@pytest.mark.asyncio
class TestIndexDocumentSync:
    async def test_sync_path_persists_milvus_ids(self, monkeypatch):
        """sync（parse-sync）路径：索引后 milvus_id 回填并 commit 落库。"""
        session = _make_session()
        _patch_session_factory(monkeypatch, session)
        db_chunks = [_db_chunk(0), _db_chunk(1)]
        monkeypatch.setattr(
            dps.chunk_repo, "list_by_document", AsyncMock(return_value=db_chunks)
        )
        monkeypatch.setattr(
            dps.indexer, "index_document", AsyncMock(return_value=["m0", "m1"])
        )
        graph_mock = AsyncMock()
        monkeypatch.setattr(dps, "build_graph_after_index", graph_mock)

        chunks = [_payload("doc-1", 0), _payload("doc-1", 1)]
        result = await dps.index_document_sync("doc-1", chunks, doc_title="t", kb_id="kb")

        assert result == ["m0", "m1"]
        assert db_chunks[0].milvus_id == "m0"
        assert db_chunks[1].milvus_id == "m1"
        session.commit.assert_awaited_once()
        graph_mock.assert_awaited_once_with("doc-1", chunks)
