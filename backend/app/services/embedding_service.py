"""Multimodal embedding service（系统模型配置驱动，双路径）。

模型配置经 system_model_service.resolve("embedding") 解析（DB 覆盖 settings 默认，
api_key 回落 DASHSCOPE_API_KEY），按模型能力选择调用路径：
- 多模态模型（qwen3-vl-embedding）：官方 dashscope SDK 的 MultiModalEmbedding.call()，
  文本与图片编码到同一向量空间
  - 独立向量：input 中每个输入（文本/图片）各返回 1 个向量
    → embed_dense / embed_query（文本）、embed_images（图片）
  - 融合向量（enable_fusion=True）：input 所有输入融合为 1 个向量
    → embed_fused（图文统一表征，如图片+所属章节上下文）
- 文本模型（text-embedding-v3 / qwen3.7-text-embedding 等 OpenAI 规范）：
  POST {base_url}/embeddings，仅支持文本；embed_images 抛错、embed_fused 仅用文本，
  图片向量能力由调用方（indexer）通过 supports_image() 预检降级。

无本地模型、无兜底策略：API Key 缺失或请求失败直接抛错，由调用方决定降级。
"""

import asyncio
import base64
import logging
from http import HTTPStatus
from typing import Union, List, Optional

import dashscope
from openai import AsyncOpenAI, RateLimitError

from app.config import get_settings
from app.services.usage_service import usage_service

settings = get_settings()
logger = logging.getLogger(__name__)

EMBEDDING_NOT_CONFIGURED_MSG = "Embedding API Key 未配置（系统环境变量 DASHSCOPE_API_KEY 或模型配置页自定义 Key）"
EMBEDDING_TEXT_ONLY_MSG = "当前向量模型仅支持文本，不支持图片向量化"

# qwen3-vl-embedding 单次请求 input 总数 ≤ 20，其中图片 ≤ 10
_TEXT_BATCH = 20
_IMAGE_BATCH = 10

# 限流（HTTP 429 / Throttling）重试：批量索引后紧接着的 embed_query 极易撞限流，
# 直接报错会导致对话链路检索 0 命中，指数退避重试后基本可自愈
_THROTTLE_MAX_RETRIES = 3
_THROTTLE_BASE_DELAY = 2.0  # 秒，退避序列 2s/4s/8s


class EmbeddingService:
    """向量化客户端（system_model_service 解析配置，保存后运行时生效）。"""

    @staticmethod
    async def _resolve() -> dict:
        """解析生效 embedding 配置（model/base_url/api_key/dimension/is_multimodal）。"""
        from app.services.system_model_service import system_model_service

        cfg = await system_model_service.resolve("embedding")
        if not cfg.get("api_key"):
            raise RuntimeError(EMBEDDING_NOT_CONFIGURED_MSG)
        return cfg

    async def supports_image(self) -> bool:
        """当前向量模型是否支持图片向量化（多模态）。"""
        from app.services.system_model_service import system_model_service

        cfg = await system_model_service.resolve("embedding")
        return bool(cfg.get("is_multimodal"))

    async def _post_contents(self, contents: List[dict], enable_fusion: bool = False) -> List[List[float]]:
        """按生效配置分发到 dashscope 多模态路径或 OpenAI 文本路径。"""
        cfg = await self._resolve()
        if cfg["is_multimodal"]:
            return await self._post_dashscope(cfg, contents, enable_fusion)
        return await self._post_openai(cfg, contents)

    async def _post_dashscope(
        self, cfg: dict, contents: List[dict], enable_fusion: bool = False
    ) -> List[List[float]]:
        """调用 MultiModalEmbedding.call，按 index 排序返回向量列表（融合模式恒返回 1 个）。

        SDK 为同步阻塞调用，用 asyncio.to_thread 包装避免阻塞事件循环。
        """
        kwargs: dict = {
            "api_key": cfg["api_key"],
            "model": cfg["model"],
            "input": contents,
            "dimension": cfg["dimension"],
        }
        if enable_fusion:
            kwargs["enable_fusion"] = True
        resp = None
        for attempt in range(_THROTTLE_MAX_RETRIES + 1):
            resp = await asyncio.to_thread(dashscope.MultiModalEmbedding.call, **kwargs)
            if resp.status_code == HTTPStatus.OK:
                break
            throttled = resp.status_code == HTTPStatus.TOO_MANY_REQUESTS or "Throttling" in str(resp.code or "")
            if throttled and attempt < _THROTTLE_MAX_RETRIES:
                delay = _THROTTLE_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Embedding 限流（HTTP %s %s），%.0fs 后重试（%d/%d）",
                    resp.status_code, resp.code, delay, attempt + 1, _THROTTLE_MAX_RETRIES,
                )
                await asyncio.sleep(delay)
                continue
            raise RuntimeError(
                f"Embedding 调用失败（HTTP {resp.status_code}）: {resp.code} {resp.message}"
            )
        embeddings = (resp.output or {}).get("embeddings") or []
        if not embeddings:
            raise RuntimeError(
                f"Embedding 响应无向量数据: {resp.code} {resp.message}"
            )
        # 用量埋点（usage: input_tokens / image_tokens / total_tokens）
        usage = getattr(resp, "usage", None) or {}
        usage_service.track(
            "embedding",
            cfg["model"],
            scene="fusion" if enable_fusion else "independent",
            prompt_tokens=int(usage.get("input_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            extra={"image_tokens": int(usage.get("image_tokens") or 0)},
        )
        sorted_items = sorted(embeddings, key=lambda x: x.get("index", 0))
        return [item["embedding"] for item in sorted_items]

    async def _post_openai(self, cfg: dict, contents: List[dict]) -> List[List[float]]:
        """OpenAI 兼容文本路径：POST {base_url}/embeddings（仅文本输入）。"""
        texts: List[str] = []
        for item in contents:
            if "image" in item:
                raise RuntimeError(EMBEDDING_TEXT_ONLY_MSG)
            texts.append(item["text"])
        client = AsyncOpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"], max_retries=0)
        kwargs: dict = {"model": cfg["model"], "input": texts}
        if cfg.get("dimension"):
            kwargs["dimensions"] = cfg["dimension"]
        resp = None
        for attempt in range(_THROTTLE_MAX_RETRIES + 1):
            try:
                resp = await client.embeddings.create(**kwargs)
                break
            except RateLimitError:
                if attempt >= _THROTTLE_MAX_RETRIES:
                    raise
                delay = _THROTTLE_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "Embedding 限流（HTTP 429），%.0fs 后重试（%d/%d）",
                    delay, attempt + 1, _THROTTLE_MAX_RETRIES,
                )
                await asyncio.sleep(delay)
        usage = getattr(resp, "usage", None)
        usage_service.track(
            "embedding",
            cfg["model"],
            scene="independent",
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
        )
        sorted_items = sorted(resp.data, key=lambda x: x.index)
        return [item.embedding for item in sorted_items]

    async def embed_dense(self, texts: Union[str, List[str]]) -> List[List[float]]:
        """文本独立向量：每条文本 1 个向量，按批（≤20 条/请求）调用。"""
        if isinstance(texts, str):
            texts = [texts]
        all_embeddings: List[List[float]] = []
        for i in range(0, len(texts), _TEXT_BATCH):
            batch = texts[i : i + _TEXT_BATCH]
            all_embeddings.extend(await self._post_contents([{"text": t} for t in batch]))
        return all_embeddings

    async def embed_query(self, query: str) -> List[float]:
        embeddings = await self.embed_dense(query)
        return embeddings[0]

    async def embed_images(self, images: List[Union[bytes, str]]) -> List[List[float]]:
        """图片独立向量：每张图 1 个向量，按批（≤10 张/请求）调用。

        images 元素：bytes（图片二进制，转 base64 Data URI）或 str
        （data URI / 公开可访问的 http(s) URL，原样透传）。
        仅多模态向量模型支持；文本模型抛 RuntimeError，由调用方预检降级。
        """
        all_embeddings: List[List[float]] = []
        for i in range(0, len(images), _IMAGE_BATCH):
            batch = images[i : i + _IMAGE_BATCH]
            all_embeddings.extend(
                await self._post_contents([{"image": self._to_image_url(img)} for img in batch])
            )
        return all_embeddings

    async def embed_fused(
        self,
        text: Optional[str] = None,
        images: Optional[List[Union[bytes, str]]] = None,
    ) -> List[float]:
        """融合向量（enable_fusion=True）：文本+图片融合为 1 个向量。

        适用于整体表征图文内容的场景（如图片+所属章节上下文入库）。
        text 与 images 至少提供其一；文本向量模型下仅用文本（无文本则抛错）。
        """
        if not await self.supports_image():
            if not text:
                raise RuntimeError(EMBEDDING_TEXT_ONLY_MSG)
            images = None
        contents: List[dict] = []
        if text:
            contents.append({"text": text})
        for img in images or []:
            contents.append({"image": self._to_image_url(img)})
        if not contents:
            raise ValueError("embed_fused 需要至少一个文本或图片输入")
        vectors = await self._post_contents(contents, enable_fusion=True)
        return vectors[0]

    @staticmethod
    def _to_image_url(image: Union[bytes, str]) -> str:
        """bytes → base64 Data URI；str（data:/http(s): URL）原样透传。"""
        if isinstance(image, bytes):
            b64 = base64.b64encode(image).decode("ascii")
            return f"data:image/png;base64,{b64}"
        return image


embedding_service = EmbeddingService()
