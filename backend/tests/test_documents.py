"""Tests for document management endpoints."""

import pytest
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from fastapi import Request
from app.main import app
from app.api.auth import get_current_user


@pytest.fixture
def override_get_current_user():
    """覆盖 get_current_user 依赖，返回一个 mock admin 用户."""
    async def fake_get_current_user(request: Request, credentials=None):
        user = MagicMock()
        user.id = "user-test-001"
        user.username = "testuser"
        user.role = "admin"
        user.status = "active"
        return user

    app.dependency_overrides[get_current_user] = fake_get_current_user
    yield
    del app.dependency_overrides[get_current_user]


@pytest.mark.asyncio
class TestDocuments:
    async def test_list_documents(self, override_get_current_user):
        """测试获取文档列表（带分页）."""
        doc = MagicMock()
        doc.id = "doc-001"
        doc.filename = "test.pdf"
        doc.original_name = "测试文档.pdf"
        doc.file_size = 102400
        doc.mime_type = "application/pdf"
        doc.oss_url = "http://minio/test.pdf"
        doc.parse_status = "completed"
        doc.parse_mode = "pymupdf"
        doc.chunk_size = 800
        doc.chunk_overlap = 100
        doc.dimension = 1536
        doc.page_count = 10
        doc.category_id = None
        from datetime import datetime, timezone
        doc.created_at = datetime.now(timezone.utc)
        doc.updated_at = datetime.now(timezone.utc)

        with patch("app.api.documents.AsyncSessionLocal") as mock_session_cls:
            session = AsyncMock()
            result_mock = MagicMock()
            result_mock.scalars.return_value.all.return_value = [doc]

            count_result = MagicMock()
            count_result.scalar_one.return_value = 1

            session.execute = AsyncMock(side_effect=[count_result, result_mock])

            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/v1/documents", params={"page": 1, "page_size": 20})


            assert resp.status_code == 200
            data = resp.json()
            assert data["code"] == 0
            assert "items" in data["data"]
            assert data["data"]["total"] == 1

    async def test_document_status_not_found(self, override_get_current_user):
        """测试查询不存在的文档状态返回 404."""
        with patch("app.api.documents.AsyncSessionLocal") as mock_session_cls:
            session = AsyncMock()
            result_mock = MagicMock()
            result_mock.scalar_one_or_none.return_value = None
            session.execute = AsyncMock(return_value=result_mock)
            session.get = AsyncMock(return_value=None)

            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/v1/documents/non-existent/status")

            assert resp.status_code == 404

    async def test_parse_document(self, override_get_current_user):
        """测试触发文档解析队列."""
        doc = MagicMock()
        doc.id = "doc-parse-001"
        doc.parse_status = "pending"
        doc.parse_mode = "pymupdf"
        doc.chunk_size = 800
        doc.chunk_overlap = 100
        doc.oss_url = "http://minio/test.pdf"
        doc.filename = "test.pdf"

        with patch("app.api.documents.AsyncSessionLocal") as mock_session_cls:
            session = AsyncMock()
            session.get = AsyncMock(return_value=doc)
            session.commit = AsyncMock()

            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("app.api.documents.trigger_parse_background") as mock_trigger:
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    resp = await client.post("/api/v1/documents/doc-parse-001/parse")

                assert resp.status_code == 200
                data = resp.json()
                assert data["code"] == 0
                assert data["data"]["message"] == "Document parsing started"
                # 无请求体时 strategy_override=None，由后台按 document/用户默认策略解析
                mock_trigger.assert_called_once_with("doc-parse-001", None)

    async def test_parse_document_with_strategy_body(self, override_get_current_user):
        """/parse 接受可选策略请求体并透传给后台任务。"""
        doc = MagicMock()
        doc.id = "doc-parse-002"
        doc.parse_status = "pending"

        with patch("app.api.documents.AsyncSessionLocal") as mock_session_cls:
            session = AsyncMock()
            session.get = AsyncMock(return_value=doc)
            session.commit = AsyncMock()

            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            # document_repo.get 走 repo（而非 session.get）
            with patch("app.api.documents.document_repo") as mock_repo, \
                 patch("app.api.documents.trigger_parse_background") as mock_trigger:
                mock_repo.get = AsyncMock(return_value=doc)
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    resp = await client.post(
                        "/api/v1/documents/doc-parse-002/parse",
                        json={"strategy_id": "strategy-abc", "chunk_size": 500},
                    )

                assert resp.status_code == 200
                mock_trigger.assert_called_once()
                override = mock_trigger.call_args.args[1]
                assert override.strategy_id == "strategy-abc"
                assert override.chunk_size == 500

    async def test_preview_chunks_with_strategy_override(self, override_get_current_user):
        """chunks/preview：strategy_id 覆盖流入 resolve_strategy；响应带 mode_used/heading/chunk_type。"""
        from app.services.document_parser import ParseStrategyConfig

        doc = MagicMock()
        doc.id = "doc-prev-001"
        doc.user_id = "user-test-001"
        doc.oss_url = "http://minio/test.pdf"
        doc.filename = "test.pdf"

        strategy = ParseStrategyConfig(parse_mode="pymupdf", chunk_size=500)
        parse_result = SimpleNamespace(
            pages=[SimpleNamespace(page_number=1)],
            raw_images=[],
            mode_used="pymupdf",
        )
        chunks = [{
            "chunk_id": "doc-prev-001_chunk_0000",
            "page": 1,
            "content": "第一段内容",
            "image_ids": ["img-1"],
            "heading": "第一章",
            "chunk_type": "table",
        }]
        vlm_cfg = {"model": "m", "base_url": "b", "api_key": "k", "detail": "high", "max_tokens": 4096}

        with patch("app.api.documents.AsyncSessionLocal") as mock_session_cls:
            session = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("app.api.documents.document_repo") as mock_repo, \
                 patch("app.api.documents.resolve_strategy", new=AsyncMock(return_value=strategy)) as mock_resolve, \
                 patch("app.api.documents.parse_config_service") as mock_pcs, \
                 patch("app.api.documents.download_file", new=AsyncMock()), \
                 patch("app.api.documents.parse_document_file", return_value=parse_result), \
                 patch("app.api.documents.split_pages_to_chunks", return_value=chunks):
                mock_repo.get = AsyncMock(return_value=doc)
                mock_pcs.resolve_vlm_for_strategy = AsyncMock(return_value=vlm_cfg)

                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    resp = await client.post(
                        "/api/v1/documents/doc-prev-001/chunks/preview",
                        json={"strategy_id": "strategy-abc", "chunk_size": 500},
                    )

        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["mode_used"] == "pymupdf"
        assert data["data"]["page_count"] == 1
        assert data["data"]["total_images"] == 0
        chunk0 = data["data"]["chunks"][0]
        assert chunk0["heading"] == "第一章"
        assert chunk0["chunk_type"] == "table"
        assert chunk0["image_ids"] == ["img-1"]
        # strategy_id / chunk_size 覆盖流入 resolve_strategy 的第 4 个参数（override）
        mock_resolve.assert_awaited_once()
        override = mock_resolve.call_args.args[3]
        assert override.strategy_id == "strategy-abc"
        assert override.chunk_size == 500
        # 系统级 VLM 配置注入 strategy（三路径统一）
        assert strategy.vlm_config == vlm_cfg
