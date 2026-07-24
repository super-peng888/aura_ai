"""Dense + sparse + multimodal embedding service.

配置全部来自 settings（app.config，系统级；修改后重启生效）：
- 文本向量（dense）：EMBEDDING_TEXT_MODEL，OpenAI 兼容 embeddings 端点；
  DASHSCOPE_API_KEY 缺失时 embed_dense 抛 RuntimeError（"不配不用"）。
- 融合向量（dense+sparse）：EMBEDDING_FUSION_MODEL 配置时，embed_sparse 调用
  该模型一次取回 sparse 向量；未配置时走内置 tokenizer 词频编码。
  （注：阿里云 Maas compatible-api 的多模态/融合向量暂不支持 OpenAI 兼容接口，
  这里按 OpenAI embeddings 响应 + 常见扩展字段做宽容解析，解析不到记 warning
  回落本地 tokenizer。）
- 多模态向量（图像）：EMBEDDING_MULTIMODAL_MODEL 配置时，embed_images 把图片
  按 OpenAI 兼容多模态输入格式转向量；未配置抛 RuntimeError（调用方按需捕获）。
"""

import asyncio
import base64
import logging
from typing import Union, List, Optional
from collections import Counter

from openai import AsyncOpenAI

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# Sparse 向量兜底实现：tokenizer 词频编码（BAAI/bge-m3 词表），不暴露为配置
_SPARSE_PROVIDER = "tokenizer"
_SPARSE_MODEL = "BAAI/bge-m3"

# dense embedding 缺 API key 时的统一报错文案（模型名有默认值，通常只差 key）
EMBEDDING_NOT_CONFIGURED_MSG = "Embedding API Key 未配置（系统环境变量 DASHSCOPE_API_KEY）"
MULTIMODAL_NOT_CONFIGURED_MSG = "多模态向量化模型未配置（EMBEDDING_MULTIMODAL_MODEL），图像 embedding 不可用"

# 融合响应中 sparse 向量的常见扩展字段（宽容解析，命中其一即可）
_SPARSE_FIELD_CANDIDATES = ("sparse_embedding", "lexical_weights", "sparse")


class SparseEmbeddingService:
    """Lightweight sparse embedding using a tokenizer's vocabulary."""

    def __init__(self):
        self.model_name = _SPARSE_MODEL
        self._tokenizer = None

    def _load(self):
        if self._tokenizer is None:
            from transformers import AutoTokenizer
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        return self._tokenizer

    def _encode_single(self, text: str) -> dict:
        tokenizer = self._load()
        tokens = tokenizer(text, add_special_tokens=False)["input_ids"]
        if not tokens:
            return {}
        counts = Counter(tokens)
        total = len(tokens)
        return {int(token_id): round(float(count) / total, 6) for token_id, count in counts.items()}

    async def embed(self, texts: Union[str, List[str]]) -> List[dict]:
        if isinstance(texts, str):
            texts = [texts]
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: [self._encode_single(t) for t in texts])


def _normalize_sparse(raw) -> Optional[dict]:
    """把融合响应里的 sparse 扩展字段宽容归一为 {int_token_id: float_weight}。

    支持 {str_id: weight} 字典与 [{"index": id, "value": w}] 列表两种常见形状；
    归一失败返回 None（调用方回落本地 tokenizer）。
    """
    if isinstance(raw, dict):
        try:
            return {int(k): float(v) for k, v in raw.items()}
        except (TypeError, ValueError):
            return None
    if isinstance(raw, list):
        out = {}
        try:
            for item in raw:
                if isinstance(item, dict):
                    idx = item.get("index", item.get("token_id"))
                    val = item.get("value", item.get("weight"))
                elif isinstance(item, (list, tuple)) and len(item) == 2:
                    idx, val = item
                else:
                    return None
                out[int(idx)] = float(val)
        except (TypeError, ValueError):
            return None
        return out
    return None


def _extract_sparse_from_response(resp) -> Optional[List[dict]]:
    """从 OpenAI 兼容 embeddings 响应中宽容提取每条输入的 sparse 向量。

    查找位置（按序）：data[i].sparse_embedding / lexical_weights / sparse
    （对象属性或字典键）。任一字段缺失或形状不识别 → None（调用方回落）。
    """
    data = getattr(resp, "data", None)
    if data is None and isinstance(resp, dict):
        data = resp.get("data")
    if not data:
        return None
    sparses: List[dict] = []
    for item in data:
        raw = None
        for field in _SPARSE_FIELD_CANDIDATES:
            if isinstance(item, dict):
                raw = item.get(field)
            else:
                raw = getattr(item, field, None)
            if raw:
                break
        sparse = _normalize_sparse(raw)
        if sparse is None:
            return None
        sparses.append(sparse)
    return sparses


class EmbeddingService:
    """OpenAI-compatible dense/sparse/multimodal embedding（settings 直读）。

    AsyncOpenAI client 懒加载且按 settings 构建一次：配置变更 = 重启生效，
    与"config.py 系统级"语义一致。
    """

    def __init__(self):
        self._client: Optional[AsyncOpenAI] = None
        self._sparse: Optional[SparseEmbeddingService] = (
            SparseEmbeddingService() if _SPARSE_PROVIDER == "tokenizer" else None
        )

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=settings.DASHSCOPE_API_KEY,
                base_url=settings.MODEL_BASE_URL or None,
            )
        return self._client

    def _require_api_key(self) -> None:
        if not settings.DASHSCOPE_API_KEY:
            raise RuntimeError(EMBEDDING_NOT_CONFIGURED_MSG)

    async def embed_dense(self, texts: Union[str, List[str]]) -> List[List[float]]:
        """文本向量（EMBEDDING_TEXT_MODEL）。行为与融合模型是否配置无关。"""
        if isinstance(texts, str):
            texts = [texts]
        self._require_api_key()
        return await self._embed_batch(self._get_client(), settings.EMBEDDING_TEXT_MODEL, texts)

    @staticmethod
    async def _embed_batch(client: AsyncOpenAI, model: str, texts: List[str]) -> List[List[float]]:
        batch_size = 128
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            resp = await client.embeddings.create(model=model, input=batch, encoding_format="float")
            sorted_data = sorted(resp.data, key=lambda x: x.index)
            all_embeddings.extend([d.embedding for d in sorted_data])
        return all_embeddings

    async def embed_sparse(self, texts: Union[str, List[str]]) -> Optional[List[dict]]:
        """Sparse 向量。

        配置了 EMBEDDING_FUSION_MODEL：调用融合模型，从响应扩展字段解析 sparse，
        解析不到记 warning 回落本地 tokenizer；未配置：直接本地 tokenizer。
        """
        if isinstance(texts, str):
            texts = [texts]
        if settings.EMBEDDING_FUSION_MODEL:
            sparses = await self._embed_sparse_fusion(texts)
            if sparses is not None:
                return sparses
            logger.warning(
                "Fusion embedding (%s) 响应未包含可解析的 sparse 向量，回落本地 tokenizer",
                settings.EMBEDDING_FUSION_MODEL,
            )
        if self._sparse is None:
            return None
        return await self._sparse.embed(texts)

    async def _embed_sparse_fusion(self, texts: List[str]) -> Optional[List[dict]]:
        """调用融合模型并提取 sparse 向量；API 失败或解析失败返回 None。"""
        try:
            self._require_api_key()
            client = self._get_client()
            resp = await client.embeddings.create(
                model=settings.EMBEDDING_FUSION_MODEL,
                input=texts,
                encoding_format="float",
            )
        except Exception as e:
            logger.warning("Fusion embedding request failed: %s", e)
            return None
        return _extract_sparse_from_response(resp)

    async def embed_query(self, query: str) -> List[float]:
        embeddings = await self.embed_dense(query)
        return embeddings[0]

    async def embed_query_sparse(self, query: str) -> Optional[dict]:
        result = await self.embed_sparse(query)
        return result[0] if result else None

    async def embed_images(self, images: List[Union[bytes, str]]) -> List[List[float]]:
        """多模态图像向量（EMBEDDING_MULTIMODAL_MODEL）。

        images 元素：bytes（图片二进制，转 base64 data URL）或 str
        （data URL / http(s) URL，原样透传）。按 OpenAI 兼容多模态输入格式
        （input 为 content parts 列表）POST {MODEL_BASE_URL}/embeddings——
        走裸 httpx 而非 SDK（SDK 对 input 的类型校验不含 content parts 形状）。
        响应按 OpenAI embeddings 形状宽容解析；未配置模型抛 RuntimeError。
        """
        if not settings.EMBEDDING_MULTIMODAL_MODEL:
            raise RuntimeError(MULTIMODAL_NOT_CONFIGURED_MSG)
        self._require_api_key()
        import httpx

        inputs = [
            [{"type": "image_url", "image_url": {"url": self._to_image_url(img)}}]
            for img in images
        ]
        url = f"{settings.MODEL_BASE_URL.rstrip('/')}/embeddings"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}"},
                json={
                    "model": settings.EMBEDDING_MULTIMODAL_MODEL,
                    "input": inputs,
                    "encoding_format": "float",
                },
            )
            resp.raise_for_status()
            data = (resp.json() or {}).get("data") or []
        sorted_data = sorted(data, key=lambda x: x.get("index", 0))
        return [d["embedding"] for d in sorted_data]

    @staticmethod
    def _to_image_url(image: Union[bytes, str]) -> str:
        """bytes → base64 data URL；str（data:/http(s): URL）原样透传。"""
        if isinstance(image, bytes):
            b64 = base64.b64encode(image).decode("ascii")
            return f"data:image/png;base64,{b64}"
        return image


embedding_service = EmbeddingService()
