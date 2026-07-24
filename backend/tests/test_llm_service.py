"""llm_service 重构后的单元测试。

覆盖：
- ChatLLM.get_model 懒加载缓存与 ChatOpenAI 参数
- LLMFactory.create 各 provider 回落（deepseek 默认 / custom 传入值 / 历史脏数据回落）
- LLMFactory.create_from_user_config 解密
- UserModelConfigService.resolve 的 custom / deepseek / 历史脏数据分支（用户 ID 从请求上下文读取）
- LLMService.generate / generate_stream / rewrite_query 签名冒烟
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.services.llm_service as llm_module
from app.services.llm_service import (
    ChatLLM,
    LLMFactory,
    LLMService,
    UserModelConfigService,
    decrypt_api_key,
    encrypt_api_key,
    settings,
)


# =============================================================================
# API Key 加解密
# =============================================================================

class TestApiKeyCrypto:
    def test_roundtrip_with_fernet(self, monkeypatch):
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", key)

        cipher = encrypt_api_key("sk-secret")
        assert cipher != "sk-secret"
        assert decrypt_api_key(cipher) == "sk-secret"

    def test_plaintext_passthrough_without_key(self, monkeypatch):
        monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", "")
        assert encrypt_api_key("sk-plain") == "sk-plain"
        assert decrypt_api_key("sk-plain") == "sk-plain"

    def test_decrypt_legacy_plaintext_with_key_configured(self, monkeypatch):
        from cryptography.fernet import Fernet

        monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", Fernet.generate_key().decode())
        # 库里存的明文旧数据解密失败时应原样返回
        assert decrypt_api_key("sk-legacy-plain") == "sk-legacy-plain"


# =============================================================================
# ChatLLM
# =============================================================================

class TestChatLLM:
    def test_get_model_lazy_cached_with_params(self):
        llm = ChatLLM(api_key="sk-k", base_url="https://example.com/v1", model="m1")
        with patch("langchain_openai.ChatOpenAI") as mock_cls:
            first = llm.get_model()
            second = llm.get_model()

        mock_cls.assert_called_once_with(
            model="m1",
            api_key="sk-k",
            base_url="https://example.com/v1",
            streaming=True,
        )
        assert first is second
        assert first is mock_cls.return_value

    def test_to_lc_messages_role_mapping(self):
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        msgs = ChatLLM._to_lc_messages([
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"},
            {"role": "unknown", "content": "x"},
            {"content": "no-role"},
        ])
        assert isinstance(msgs[0], SystemMessage)
        assert isinstance(msgs[1], HumanMessage)
        assert isinstance(msgs[2], AIMessage)
        assert isinstance(msgs[3], HumanMessage)  # 未知 role 回落 user
        assert isinstance(msgs[4], HumanMessage)
        assert [m.content for m in msgs] == ["s", "u", "a", "x", "no-role"]


# =============================================================================
# LLMFactory
# =============================================================================

class TestLLMFactory:
    @pytest.mark.parametrize("provider", [None, "deepseek", "qwen", "glm", "openai", "azure", "garbage"])
    def test_non_custom_providers_fall_back_to_deepseek(self, provider):
        """deepseek/qwen/glm/None/历史脏数据一律回落系统默认 deepseek。"""
        llm = LLMFactory.create(provider=provider)
        assert isinstance(llm, ChatLLM)
        assert llm.api_key == settings.DEEPSEEK_API_KEY
        assert llm.base_url == settings.DEEPSEEK_BASE_URL
        assert llm.model == settings.DEEPSEEK_CHAT_MODEL

    def test_custom_uses_passed_values(self):
        llm = LLMFactory.create(
            provider="custom",
            api_key="sk-user",
            base_url="https://user.example.com/v1",
            model="user-model",
        )
        assert llm.api_key == "sk-user"
        assert llm.base_url == "https://user.example.com/v1"
        assert llm.model == "user-model"

    def test_custom_missing_values_raise(self):
        """custom 缺任一项（api_key/base_url/model）→ ValueError，不再回落 env 默认。"""
        with pytest.raises(ValueError, match="自定义模型配置不完整"):
            LLMFactory.create(provider="custom")

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"api_key": "sk-only"},
            {"base_url": "https://only.example.com/v1"},
            {"model": "only-model"},
            {"api_key": "sk-k", "base_url": "https://k.example.com/v1"},  # 缺 model
        ],
    )
    def test_explicit_partial_params_raise(self, kwargs):
        """显式传参但带不齐时同样报错（custom 语义）。"""
        with pytest.raises(ValueError, match="自定义模型配置不完整"):
            LLMFactory.create(**kwargs)

    def test_explicit_full_params_without_provider_use_custom_semantics(self):
        """显式带齐 api_key/base_url/model 时按 custom 处理。"""
        llm = LLMFactory.create(
            api_key="sk-explicit",
            base_url="https://explicit.example.com/v1",
            model="explicit-model",
        )
        assert llm.api_key == "sk-explicit"
        assert llm.base_url == "https://explicit.example.com/v1"
        assert llm.model == "explicit-model"

    def test_create_from_user_config_none_returns_default(self):
        llm = LLMFactory.create_from_user_config(None)
        assert llm.model == settings.DEEPSEEK_CHAT_MODEL

    def test_create_from_user_config_preset(self):
        llm = LLMFactory.create_from_user_config({"provider": "deepseek"})
        assert llm.model == settings.DEEPSEEK_CHAT_MODEL

    def test_create_from_user_config_historical_qwen_falls_back(self):
        llm = LLMFactory.create_from_user_config({"provider": "qwen"})
        assert llm.model == settings.DEEPSEEK_CHAT_MODEL

    def test_create_from_user_config_decrypts_api_key(self, monkeypatch):
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        monkeypatch.setattr(settings, "API_KEY_ENCRYPTION_KEY", key)
        cipher = Fernet(key.encode()).encrypt(b"sk-secret").decode()

        llm = LLMFactory.create_from_user_config({
            "provider": "custom",
            "api_key": cipher,
            "base_url": "https://user.example.com/v1",
            "model": "user-model",
        })
        assert llm.api_key == "sk-secret"
        assert llm.base_url == "https://user.example.com/v1"
        assert llm.model == "user-model"


# =============================================================================
# UserModelConfigService.resolve（用户 ID 从请求上下文 request_context 读取）
# =============================================================================

def _mock_resolve_deps(monkeypatch, user, custom=None):
    """mock DB session / repo / cache，使 resolve 直接执行 _fetch_from_db。"""
    session = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(llm_module, "AsyncSessionLocal", lambda: cm)

    mock_get = AsyncMock(return_value=user)
    monkeypatch.setattr(llm_module.user_repo, "get", mock_get)
    monkeypatch.setattr(
        llm_module.user_model_config_repo,
        "get_current_by_user",
        AsyncMock(return_value=custom),
    )

    async def fake_cache_get_or_set(key, fetch, ttl=None, prefix=""):
        return await fetch()

    monkeypatch.setattr(llm_module, "cache_get_or_set", fake_cache_get_or_set)
    return mock_get


def _make_user(default_model_id):
    user = MagicMock()
    user.default_model_id = default_model_id
    return user


class TestUserModelConfigServiceResolve:
    @pytest.fixture(autouse=True)
    def _clean_user_context(self):
        """每个用例在隔离的用户上下文中运行，避免 ContextVar 串测试。"""
        from app.utils.request_context import current_user_id

        token = current_user_id.set(None)
        yield
        current_user_id.reset(token)

    @pytest.mark.asyncio
    async def test_no_request_context_returns_empty(self):
        """无请求上下文（worker/CLI/脚本）：user_id 为 None → 返回 {} 走系统默认。"""
        assert await UserModelConfigService.resolve() == {}

    @pytest.mark.asyncio
    async def test_context_user_id_is_used(self, monkeypatch):
        """context 设置后 resolve 读到正确的 user_id 并据此查库。"""
        from app.utils.request_context import set_current_user_id

        mock_get = _mock_resolve_deps(monkeypatch, user=_make_user("deepseek"))
        set_current_user_id("u-ctx")

        assert await UserModelConfigService.resolve() == {"provider": "deepseek"}
        assert mock_get.await_args.args[1] == "u-ctx"

    @pytest.mark.asyncio
    async def test_user_not_found_returns_empty(self, monkeypatch):
        from app.utils.request_context import set_current_user_id

        _mock_resolve_deps(monkeypatch, user=None)
        set_current_user_id("u-1")
        assert await UserModelConfigService.resolve() == {}

    @pytest.mark.asyncio
    async def test_deepseek_default(self, monkeypatch):
        from app.utils.request_context import set_current_user_id

        _mock_resolve_deps(monkeypatch, user=_make_user("deepseek"))
        set_current_user_id("u-1")
        assert await UserModelConfigService.resolve() == {"provider": "deepseek"}

    @pytest.mark.asyncio
    async def test_none_default_model_id_falls_back_to_deepseek(self, monkeypatch):
        from app.utils.request_context import set_current_user_id

        _mock_resolve_deps(monkeypatch, user=_make_user(None))
        set_current_user_id("u-1")
        assert await UserModelConfigService.resolve() == {"provider": "deepseek"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("dirty", ["qwen", "glm", "openai", "whatever"])
    async def test_historical_dirty_data_falls_back_to_deepseek(self, monkeypatch, dirty):
        """历史 qwen/glm 等脏数据自动回落系统默认，不报错。"""
        from app.utils.request_context import set_current_user_id

        _mock_resolve_deps(monkeypatch, user=_make_user(dirty))
        set_current_user_id("u-1")
        assert await UserModelConfigService.resolve() == {"provider": "deepseek"}

    @pytest.mark.asyncio
    async def test_custom_reads_user_model_configs(self, monkeypatch):
        from app.utils.request_context import set_current_user_id

        custom = MagicMock()
        custom.model = "user-model"
        custom.api_key = "sk-plain"  # 明文/解密失败均原样返回
        custom.base_url = "https://user.example.com/v1"
        custom.max_tokens = 4096
        custom.temperature = 0.7
        custom.top_p = 1.0
        custom.timeout = 60
        _mock_resolve_deps(monkeypatch, user=_make_user("custom"), custom=custom)
        set_current_user_id("u-1")

        result = await UserModelConfigService.resolve()
        assert result == {
            "provider": "custom",
            "model": "user-model",
            "api_key": "sk-plain",
            "base_url": "https://user.example.com/v1",
            "max_tokens": 4096,
            "temperature": 0.7,
            "top_p": 1.0,
            "timeout": 60,
        }

    @pytest.mark.asyncio
    async def test_custom_without_config_row_falls_back_to_deepseek(self, monkeypatch):
        from app.utils.request_context import set_current_user_id

        _mock_resolve_deps(monkeypatch, user=_make_user("custom"), custom=None)
        set_current_user_id("u-1")
        assert await UserModelConfigService.resolve() == {"provider": "deepseek"}


# =============================================================================
# LLMService 签名冒烟
# =============================================================================

class TestLLMServiceSmoke:
    @pytest.mark.asyncio
    async def test_generate(self):
        service = LLMService()
        with patch.object(ChatLLM, "generate", new=AsyncMock(return_value="ok")) as mock_gen:
            result = await service.generate(
                [{"role": "user", "content": "hi"}],
                temperature=0.5,
                max_tokens=16,
            )
        assert result == "ok"
        mock_gen.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generate_stream(self):
        async def fake_stream(self, messages, temperature=0.7, max_tokens=None):
            yield "he"
            yield "llo"

        service = LLMService()
        with patch.object(ChatLLM, "generate_stream", new=fake_stream):
            chunks = [c async for c in service.generate_stream([{"role": "user", "content": "hi"}])]
        assert chunks == ["he", "llo"]

    @pytest.mark.asyncio
    async def test_rewrite_query_strips_and_falls_back(self):
        service = LLMService()
        with patch.object(ChatLLM, "generate", new=AsyncMock(return_value="  rewritten q  ")):
            assert await service.rewrite_query("q") == "rewritten q"
        # 空改写结果回落原 query
        with patch.object(ChatLLM, "generate", new=AsyncMock(return_value="   ")):
            assert await service.rewrite_query("q") == "q"

    @pytest.mark.asyncio
    async def test_generate_with_citations(self):
        async def fake_stream(self, messages, temperature=0.7, max_tokens=None):
            # 引用编号应拼进 system prompt
            assert "[Citation 1]" in messages[0]["content"]
            yield "answer"

        service = LLMService()
        with patch.object(ChatLLM, "generate_stream", new=fake_stream):
            chunks = [
                c
                async for c in service.generate_with_citations(
                    "q",
                    [{"content": "ctx", "page_number": 3}],
                )
            ]
        assert chunks == ["answer"]
