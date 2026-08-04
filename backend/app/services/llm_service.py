"""
LLM Service — 用户级动态大语言模型调用层（重构版）

架构说明：
- 系统默认模型（deepseek）：API Key 从系统环境变量读取，用户无需配置
- 自定义模型（custom）：OpenAI 兼容端点，用户在前端配置参数，API Key 加密存储在 user_model_configs 表
- 所有 provider 均为 OpenAI 兼容协议，统一由 ChatLLM（ChatOpenAI 封装）调用，无需按厂商分子类
- 前端只传 provider，后端通过 UserModelConfigService 查数据库/Redis 解析完整配置
- 为提高性能，用户模型配置缓存到 Redis（TTL 300s），配置更新时自动清除缓存

API Key 传输说明：
- 前端 → 后端：通过 HTTPS 传输明文即可，TLS 已加密通道
- 后端 → 数据库：使用 Fernet 对称加密存储
"""

from __future__ import annotations

from typing import AsyncIterator, List, Optional

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage
from langchain_core.language_models.chat_models import BaseChatModel

from app.config import get_settings
from app.db.base import AsyncSessionLocal
from app.db.repository import user_repo
from app.services.usage_service import usage_service
from app.utils.cache import cache_get_or_set, cache_delete
from app.utils.request_context import get_current_user_id

settings = get_settings()


# =============================================================================
# API Key 加密工具
# =============================================================================

def encrypt_api_key(plain_text: str) -> str:
    """
    使用 Fernet 对称加密 API Key。

    如果未配置加密密钥（API_KEY_ENCRYPTION_KEY 为空），则返回原值（仅开发环境）。
    生产环境必须在 .env 中配置 API_KEY_ENCRYPTION_KEY。
    """
    if not plain_text:
        return plain_text
    fernet = settings.get_fernet()
    if fernet is None:
        return plain_text
    return fernet.encrypt(plain_text.encode()).decode()


def decrypt_api_key(cipher_text: str) -> str:
    """使用 Fernet 对称解密 API Key。"""
    if not cipher_text:
        return cipher_text
    fernet = settings.get_fernet()
    if fernet is None:
        return cipher_text
    try:
        return fernet.decrypt(cipher_text.encode()).decode()
    except Exception:
        # 解密失败可能是明文存储的旧数据，直接返回
        return cipher_text


# =============================================================================
# 统一 LLM 客户端（所有 provider 均为 OpenAI 兼容协议）
# =============================================================================

class ChatLLM:
    """OpenAI 兼容端点的统一 LLM 客户端（系统默认 deepseek 与用户自定义模型共用）。"""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self._model: Optional[BaseChatModel] = None

    def get_model(self) -> BaseChatModel:
        """返回配置好的 LangChain ChatModel 实例（懒加载并缓存）。"""
        if self._model is None:
            from langchain_openai import ChatOpenAI
            self._model = ChatOpenAI(
                model=self.model,
                api_key=self.api_key,
                base_url=self.base_url,
                streaming=True,
                stream_usage=True,  # 流式响应末尾 chunk 携带 usage（token 用量埋点用）
            )
        return self._model

    def _track_usage(self, usage_metadata: Optional[dict], scene: str) -> None:
        """LangChain usage_metadata → 用量埋点（无 usage 时仅计调用次数）。"""
        um = usage_metadata or {}
        usage_service.track(
            "llm",
            self.model,
            scene=scene,
            prompt_tokens=int(um.get("input_tokens") or 0),
            completion_tokens=int(um.get("output_tokens") or 0),
            total_tokens=int(um.get("total_tokens") or 0),
        )

    async def generate(
        self,
        messages: List[dict],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        scene: str = "generate",
    ) -> str:
        model = self.get_model()
        lc_messages = self._to_lc_messages(messages)
        result = await model.ainvoke(lc_messages, config={"temperature": temperature, "max_tokens": max_tokens})
        self._track_usage(getattr(result, "usage_metadata", None), scene)
        return result.content or ""

    async def generate_stream(
        self,
        messages: List[dict],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        scene: str = "chat",
    ) -> AsyncIterator[str]:
        model = self.get_model()
        lc_messages = self._to_lc_messages(messages)
        usage_metadata = None
        async for chunk in model.astream(lc_messages, config={"temperature": temperature, "max_tokens": max_tokens}):
            if getattr(chunk, "usage_metadata", None):
                usage_metadata = chunk.usage_metadata
            content = chunk.content
            if content:
                yield content
        self._track_usage(usage_metadata, scene)

    @staticmethod
    def _to_lc_messages(messages: List[dict]) -> List[BaseMessage]:
        mapping = {"system": SystemMessage, "user": HumanMessage, "assistant": AIMessage}
        result: List[BaseMessage] = []
        for m in messages:
            role = m.get("role", "user")
            cls = mapping.get(role, HumanMessage)
            result.append(cls(content=m.get("content", "")))
        return result


# =============================================================================
# 工厂
# =============================================================================

class LLMFactory:
    """根据配置创建 ChatLLM 实例。"""

    @staticmethod
    def create(
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> ChatLLM:
        """
        provider 语义：
        - "deepseek"：系统默认对话模型；调用方（UserModelConfigService）已解析好
          完整字段时直接使用，字段缺失时回落 settings.DEEPSEEK_*（旧缓存/直调兼容）
        - "system"：系统通用模型列表行（调用方已按行 id 解析好字段）；
          字段不全时回落系统默认 deepseek，不报错
        - "custom"（或显式传了 api_key/base_url/model 之一）：用户自定义 OpenAI 兼容端点，
          api_key / base_url / model 必须带齐，缺任一项抛 ValueError（不再回落 env 默认）
        - 其他任何值（qwen / glm / None / 历史脏数据）：一律回落系统默认 deepseek
        """
        provider = (provider or "").lower()

        if provider == "deepseek":
            return ChatLLM(
                api_key=api_key or settings.DEEPSEEK_API_KEY,
                base_url=base_url or settings.DEEPSEEK_BASE_URL,
                model=model or settings.DEEPSEEK_CHAT_MODEL,
            )

        if provider == "system":
            if api_key and base_url and model:
                return ChatLLM(api_key=api_key, base_url=base_url, model=model)
            return ChatLLM(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
                model=settings.DEEPSEEK_CHAT_MODEL,
            )

        if provider == "custom" or api_key or base_url or model:
            if not (api_key and base_url and model):
                raise ValueError("自定义模型配置不完整")
            return ChatLLM(api_key=api_key, base_url=base_url, model=model)

        return ChatLLM(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            model=settings.DEEPSEEK_CHAT_MODEL,
        )

    @staticmethod
    def create_from_user_config(user_config: Optional[dict]) -> ChatLLM:
        """
        从用户配置字典创建 LLM 实例（兼容旧接口）。
        """
        if not user_config:
            return LLMFactory.create()

        api_key = decrypt_api_key(user_config.get("api_key", ""))
        return LLMFactory.create(
            provider=user_config.get("provider"),
            api_key=api_key or None,
            base_url=user_config.get("base_url"),
            model=user_config.get("model"),
        )


# =============================================================================
# 用户模型配置解析服务（带 Redis 缓存）
# =============================================================================

class UserModelConfigService:
    """
    解析用户绑定的模型配置。

    逻辑：
    1. 查 Redis 缓存
    2. 缓存未命中 → 查数据库
       - default_model_id 存 provider_models.id：系统模型 → provider "system"，
         本人私有模型 → provider "custom"（携带对话参数）
       - 其余（NULL / 历史脏值 / 绑定已失效）：跟随系统默认对话模型；
         系统无 text 模型时回落 {"provider": "deepseek"}
    3. 写入 Redis（TTL 300s）
    4. 配置更新时调用 invalidate_cache 清除缓存
    """

    CACHE_PREFIX = "user_model:"
    CACHE_TTL = 300

    @staticmethod
    async def resolve() -> dict:
        """
        解析当前用户模型配置，返回配置字典供 LLMFactory 使用。

        用户 ID 从请求上下文（app.utils.request_context）读取，不再由调用方透传。
        无请求上下文（index_worker / CLI / evals 脚本）时 user_id 为 None，
        返回 {} 走系统默认模型（deepseek）——与改造前语义一致。
        """
        user_id = get_current_user_id()
        if not user_id:
            return {}

        cache_key = f"{UserModelConfigService.CACHE_PREFIX}{user_id}"

        async def _fetch_from_db() -> dict:
            async with AsyncSessionLocal() as session:
                user = await user_repo.get(session, user_id)
                if not user:
                    return {}
                bound = user.default_model_id

            from app.services.system_model_service import SystemModelService  # 懒导入避免循环依赖

            # 绑定具体模型（provider_models.id）：系统模型 → system 分支，
            # 本人私有模型 → custom 分支携带对话参数；失效/越权 → 穿透系统默认对话模型
            if bound and len(bound) == 36:
                cfg = await SystemModelService.resolve_model_by_id(bound, user_id)
                if cfg:
                    if cfg["is_system"]:
                        return {
                            "provider": "system",
                            "model": cfg["model"],
                            "api_key": cfg["api_key"],
                            "base_url": cfg["base_url"],
                        }
                    return {
                        "provider": "custom",
                        "model": cfg["model"],
                        "api_key": cfg["api_key"],
                        "base_url": cfg["base_url"],
                        "max_tokens": cfg["max_tokens"],
                        "temperature": cfg["temperature"],
                        "top_p": cfg["top_p"],
                        "timeout": cfg["timeout"],
                    }

            # 未绑定 / 'deepseek'·'custom' 等历史脏值 / 绑定已失效 → 跟随系统默认
            # 对话模型：resolve("chat") 回落链为系统最早 text 模型 → 系统 multi_modal 模型；
            # 两者都无则回落 deepseek（字段由 LLMFactory 回落 settings.DEEPSEEK_*）
            chat_cfg = await SystemModelService.resolve("chat")
            if chat_cfg.get("assigned"):
                return {
                    "provider": "system",
                    "model": chat_cfg["model"],
                    "api_key": chat_cfg["api_key"],
                    "base_url": chat_cfg["base_url"],
                }
            return {"provider": "deepseek"}

        try:
            return await cache_get_or_set(
                cache_key,
                _fetch_from_db,
                ttl=UserModelConfigService.CACHE_TTL,
                prefix="",
            ) or {}
        except Exception as e:
            print(f"[UserModelConfigService] resolve error: {e}")
            return {}

    @staticmethod
    async def invalidate_cache(user_id: str) -> None:
        """用户修改模型配置后，清除 Redis 缓存。"""
        cache_key = f"{UserModelConfigService.CACHE_PREFIX}{user_id}"
        try:
            await cache_delete(cache_key, prefix="")
        except Exception as e:
            print(f"[UserModelConfigService] invalidate cache error: {e}")


# =============================================================================
# 统一服务入口：LLMService（用户级动态）
# =============================================================================

class LLMService:
    """
    用户级动态 LLM 服务。

    重构后：
    - 用户身份从请求上下文（app.utils.request_context）读取，不再透传 user_id
    - user_config 显式覆盖参数保留（测试与特殊调用用）；为空时自动通过
      UserModelConfigService.resolve() 按上下文用户查数据库/Redis
    """

    @staticmethod
    def get_llm(user_config: Optional[dict] = None) -> ChatLLM:
        """
        获取 LLM 实例。

        同步方法：优先使用传入的 user_config；如果为空，回退到系统默认。
        异步调用方直接调用业务方法（generate 等），内部会按请求上下文解析配置。
        """
        if user_config:
            return LLMFactory.create_from_user_config(user_config)
        return LLMFactory.create()

    @staticmethod
    async def _resolve_config(user_config: Optional[dict]) -> dict:
        """内部：解析最终配置（user_config 优先，否则按请求上下文用户解析）。"""
        if user_config:
            return user_config
        return await UserModelConfigService.resolve()

    # -------------------------------------------------------------------------
    # 基础生成接口
    # -------------------------------------------------------------------------
    async def generate(
        self,
        messages: List[dict],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        user_config: Optional[dict] = None,
        scene: str = "generate",
    ) -> str:
        config = await self._resolve_config(user_config)
        llm = self.get_llm(config)
        return await llm.generate(messages, temperature, max_tokens, scene=scene)

    async def generate_stream(
        self,
        messages: List[dict],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        user_config: Optional[dict] = None,
        scene: str = "chat",
    ) -> AsyncIterator[str]:
        config = await self._resolve_config(user_config)
        llm = self.get_llm(config)
        async for delta in llm.generate_stream(messages, temperature, max_tokens, scene=scene):
            yield delta

    # -------------------------------------------------------------------------
    # 业务封装：查询改写
    # -------------------------------------------------------------------------
    async def rewrite_query(
        self,
        query: str,
        conversation_history: Optional[List[dict]] = None,
        user_config: Optional[dict] = None,
    ) -> str:
        system_prompt = (
            "You are a query optimization assistant for a technical document retrieval system.\n\n"
            "Your task is to rewrite the user's query to improve search results. You should:\n"
            "1. Keep the rewritten query in the SAME LANGUAGE as the original query "
            "(never translate, e.g. a Chinese query must stay Chinese)\n"
            "2. Preserve domain-specific terms, codes, standard names and acronyms VERBATIM "
            "(e.g. UN/EDIFACT, UNH, ISO 9001) — do not expand or replace them\n"
            "3. Add a few relevant synonyms or related terms when helpful\n"
            "4. Keep the original intent; keep the query concise (no longer than ~2x the original)\n"
            "5. Output ONLY the rewritten query, no explanation"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Rewrite this query for better document search:\n\n{query}"},
        ]
        config = await self._resolve_config(user_config)
        llm = self.get_llm(config)
        rewritten = await llm.generate(messages, temperature=0.3, max_tokens=200, scene="rewrite")
        return rewritten.strip() or query

    # -------------------------------------------------------------------------
    # 业务封装：带引用的 RAG 回答生成
    # -------------------------------------------------------------------------
    async def generate_with_citations(
        self,
        query: str,
        contexts: List[dict],
        conversation_history: Optional[List[dict]] = None,
        temperature: float = 0.7,
        user_memory: str = "",
        user_config: Optional[dict] = None,
    ) -> AsyncIterator[str]:
        context_parts = []
        for i, ctx in enumerate(contexts):
            page_info = f" (Page {ctx.get('page_number', 'N/A')})" if ctx.get("page_number") else ""
            context_parts.append(f"[Citation {i + 1}]{page_info}\n{ctx['content']}\n")
        context_str = "\n".join(context_parts)

        system_prompt = f"""You are a helpful AI assistant. Use the provided document excerpts to answer the user's question.

Instructions:
1. Base your answer primarily on the provided citations
2. When referencing information, cite the source like [1], [2], etc.
3. When the user asks for the exact content of a message, code block, configuration or document,
   reproduce it VERBATIM from the citations — character for character. NEVER invent, rewrite,
   "complete" or substitute your own version of content that exists in the citations
4. If the context includes image placeholders [IMG:xxx], describe what the image shows based on surrounding text
5. Be concise but thorough
6. If the answer is not in the provided context, say so clearly — do not fabricate an answer from general knowledge

Context:
{context_str}
"""
        if user_memory:
            system_prompt += f"\n## User Background\n{user_memory}\n"

        messages: List[dict] = [{"role": "system", "content": system_prompt}]
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": query})

        config = await self._resolve_config(user_config)
        llm = self.get_llm(config)
        async for delta in llm.generate_stream(messages, temperature=temperature, scene="chat"):
            yield delta


# =============================================================================
# 向后兼容的全局实例（不带用户配置时使用）
# =============================================================================

llm_service = LLMService()
