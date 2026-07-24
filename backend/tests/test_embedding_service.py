"""Tests for embedding_service（settings 直读的 dense / fusion sparse / multimodal embedding）。

覆盖：
- 文本 dense：DASHSCOPE_API_KEY 缺失 → RuntimeError；client 按 settings 懒加载一次
- 融合 sparse：EMBEDDING_FUSION_MODEL 配置时从响应扩展字段解析 sparse，
  扩展字段缺失 / 请求失败 → 回落本地 tokenizer；未配置 → 直接本地 tokenizer
- 多模态 embed_images：未配置 → RuntimeError；配置后请求形状（content parts + base64 data URL）
"""

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import embedding_service as es_module
from app.services.embedding_service import EmbeddingService


def _set_settings(monkeypatch, **overrides):
    """覆盖 embedding_service 模块内 settings 的字段。"""
    for key, value in overrides.items():
        monkeypatch.setattr(es_module.settings, key, value)


@pytest.fixture
def configured(monkeypatch):
    """settings 已配置（key + 文本模型），fusion/multimodal 默认未配置。"""
    _set_settings(
        monkeypatch,
        DASHSCOPE_API_KEY="sk-test",
        MODEL_BASE_URL="https://maas.example.com/v1",
        EMBEDDING_TEXT_MODEL="qwen3.7-text-embedding",
        EMBEDDING_FUSION_MODEL="",
        EMBEDDING_MULTIMODAL_MODEL="",
    )


@pytest.mark.asyncio
class TestDenseConfig:
    async def test_missing_api_key_raises_runtime_error(self, monkeypatch):
        """DASHSCOPE_API_KEY 为空 → RuntimeError（"不配不用"）。"""
        _set_settings(monkeypatch, DASHSCOPE_API_KEY="")
        service = EmbeddingService()
        with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
            await service.embed_dense(["hello"])

    async def test_missing_api_key_raises_on_query(self, monkeypatch):
        _set_settings(monkeypatch, DASHSCOPE_API_KEY="")
        service = EmbeddingService()
        with pytest.raises(RuntimeError, match="Embedding API Key 未配置"):
            await service.embed_query("hello")

    async def test_configured_embeds_and_caches_client(self, configured):
        """配置后：client 懒加载构建一次复用，model 来自 settings。"""
        service = EmbeddingService()
        fake_resp = SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0.1, 0.2])])
        with patch("app.services.embedding_service.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.embeddings.create = AsyncMock(return_value=fake_resp)
            mock_openai.return_value = mock_client

            first = await service.embed_dense(["甲"])
            second = await service.embed_dense(["乙"])

        mock_openai.assert_called_once_with(api_key="sk-test", base_url="https://maas.example.com/v1")
        assert mock_client.embeddings.create.await_count == 2
        assert mock_client.embeddings.create.call_args.kwargs["model"] == "qwen3.7-text-embedding"
        assert first == [[0.1, 0.2]]
        assert second == [[0.1, 0.2]]


@pytest.mark.asyncio
class TestFusionSparse:
    def _fusion_resp(self, sparse_field="sparse_embedding"):
        item = SimpleNamespace(index=0, embedding=[0.1], sparse_embedding=None, lexical_weights=None, sparse=None)
        setattr(item, sparse_field, {"100": 0.5, "200": 0.25})
        return SimpleNamespace(data=[item])

    async def test_fusion_configured_parses_sparse_extension(self, configured, monkeypatch):
        """配置融合模型：从响应 sparse_embedding 扩展字段解析出 {int_id: weight}。"""
        _set_settings(monkeypatch, EMBEDDING_FUSION_MODEL="qwen3.7-fusion-embedding")
        service = EmbeddingService()
        with patch("app.services.embedding_service.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.embeddings.create = AsyncMock(return_value=self._fusion_resp())
            mock_openai.return_value = mock_client
            result = await service.embed_sparse(["你好"])

        assert mock_client.embeddings.create.call_args.kwargs["model"] == "qwen3.7-fusion-embedding"
        assert result == [{100: 0.5, 200: 0.25}]

    async def test_fusion_parses_lexical_weights_fallback_field(self, configured, monkeypatch):
        """扩展字段名为 lexical_weights 时同样可解析。"""
        _set_settings(monkeypatch, EMBEDDING_FUSION_MODEL="fusion-m")
        service = EmbeddingService()
        with patch("app.services.embedding_service.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.embeddings.create = AsyncMock(
                return_value=self._fusion_resp(sparse_field="lexical_weights")
            )
            mock_openai.return_value = mock_client
            result = await service.embed_sparse(["你好"])
        assert result == [{100: 0.5, 200: 0.25}]

    async def test_fusion_parses_list_shape(self, configured, monkeypatch):
        """sparse 为 [{"index": id, "value": w}] 列表形状时也可归一。"""
        _set_settings(monkeypatch, EMBEDDING_FUSION_MODEL="fusion-m")
        item = SimpleNamespace(
            index=0, embedding=[0.1], lexical_weights=None, sparse=None,
            sparse_embedding=[{"index": "7", "value": 0.9}],
        )
        service = EmbeddingService()
        with patch("app.services.embedding_service.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.embeddings.create = AsyncMock(return_value=SimpleNamespace(data=[item]))
            mock_openai.return_value = mock_client
            result = await service.embed_sparse(["你好"])
        assert result == [{7: 0.9}]

    async def test_fusion_missing_sparse_field_falls_back_to_tokenizer(self, configured, monkeypatch):
        """响应无可解析 sparse 扩展字段 → 记 warning 回落本地 tokenizer。"""
        _set_settings(monkeypatch, EMBEDDING_FUSION_MODEL="fusion-m")
        service = EmbeddingService()
        service._sparse = MagicMock()
        service._sparse.embed = AsyncMock(return_value=[{1: 1.0}])
        plain_resp = SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0.1])])
        with patch("app.services.embedding_service.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.embeddings.create = AsyncMock(return_value=plain_resp)
            mock_openai.return_value = mock_client
            result = await service.embed_sparse(["你好"])
        service._sparse.embed.assert_awaited_once()
        assert result == [{1: 1.0}]

    async def test_fusion_request_failure_falls_back_to_tokenizer(self, configured, monkeypatch):
        """融合模型 API 调用失败 → 回落本地 tokenizer，不抛错。"""
        _set_settings(monkeypatch, EMBEDDING_FUSION_MODEL="fusion-m")
        service = EmbeddingService()
        service._sparse = MagicMock()
        service._sparse.embed = AsyncMock(return_value=[{2: 1.0}])
        with patch("app.services.embedding_service.AsyncOpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_client.embeddings.create = AsyncMock(side_effect=Exception("boom"))
            mock_openai.return_value = mock_client
            result = await service.embed_sparse(["你好"])
        assert result == [{2: 1.0}]

    async def test_fusion_not_configured_uses_tokenizer_directly(self, configured):
        """未配置融合模型：直接走本地 tokenizer，不发 API 请求。"""
        service = EmbeddingService()
        service._sparse = MagicMock()
        service._sparse.embed = AsyncMock(return_value=[{3: 1.0}])
        with patch("app.services.embedding_service.AsyncOpenAI") as mock_openai:
            result = await service.embed_sparse(["你好"])
        mock_openai.assert_not_called()
        assert result == [{3: 1.0}]


@pytest.mark.asyncio
class TestMultimodalImages:
    async def test_unconfigured_raises_runtime_error(self, configured):
        """EMBEDDING_MULTIMODAL_MODEL 未配置 → RuntimeError（调用方按需捕获）。"""
        service = EmbeddingService()
        with pytest.raises(RuntimeError, match="多模态向量化模型未配置"):
            await service.embed_images([b"\x89PNG"])

    async def test_configured_request_shape(self, configured, monkeypatch):
        """配置后：POST {MODEL_BASE_URL}/embeddings，input 为 image_url content parts，
        bytes 转 base64 data URL，http(s) URL 原样透传。"""
        _set_settings(monkeypatch, EMBEDDING_MULTIMODAL_MODEL="qwen3-vl-embedding")
        service = EmbeddingService()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={
            "data": [
                {"index": 1, "embedding": [0.2]},
                {"index": 0, "embedding": [0.1]},
            ]
        })
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        png_bytes = b"\x89PNG-fake"
        with patch("httpx.AsyncClient", return_value=mock_client) as mock_ctor:
            result = await service.embed_images([png_bytes, "https://oss.example.com/a.png"])

        assert mock_ctor.call_args.kwargs["timeout"] == 60.0
        url = mock_client.post.call_args.args[0]
        assert url == "https://maas.example.com/v1/embeddings"
        headers = mock_client.post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer sk-test"
        payload = mock_client.post.call_args.kwargs["json"]
        assert payload["model"] == "qwen3-vl-embedding"
        expected_b64 = base64.b64encode(png_bytes).decode("ascii")
        assert payload["input"] == [
            [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{expected_b64}"}}],
            [{"type": "image_url", "image_url": {"url": "https://oss.example.com/a.png"}}],
        ]
        # 按 index 排序还原顺序
        assert result == [[0.1], [0.2]]


class TestSparseDefaults:
    def test_sparse_is_builtin_tokenizer(self):
        """sparse 兜底实现固定为 tokenizer / BAAI-bge-m3，不再来自 env 配置。"""
        service = EmbeddingService()
        assert service._sparse is not None
        assert service._sparse.model_name == "BAAI/bge-m3"
