"""系统级解析配置服务测试：内置默认 / DB 覆盖 / api_key 加解密与掩码回显 / save 语义。

全部 mock（Redis cache_get_or_set 透传、AsyncSessionLocal、parse_config_repo），
不触碰真实数据库与 Redis。
"""

from types import SimpleNamespace
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from app.services.llm_service import decrypt_api_key, encrypt_api_key
from app.services.parse_config_service import ParseConfigService, _mask_api_key


async def _cache_passthrough(key, factory, ttl=300, prefix=None):
    """跳过 Redis，直接执行 factory。"""
    return await factory()


def _mock_session_local(session=None):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session or AsyncMock())
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


def _make_row(**overrides):
    """构造 system_parse_config 行 mock（默认全 NULL = 回落内置默认）。"""
    row = SimpleNamespace(
        id="cfg-1",
        vlm_model=None,
        vlm_base_url=None,
        vlm_api_key=None,
        vlm_detail_level=None,
        vlm_max_tokens=None,
    )
    for k, v in overrides.items():
        setattr(row, k, v)
    return row


def _patch_common(repo_row=None, session=None):
    """返回一组 patch：cache 透传 + mock session + mock repo（get_singleton 返回 repo_row）。"""
    mock_repo = MagicMock()
    mock_repo.get_singleton = AsyncMock(return_value=repo_row)
    mock_repo.upsert = AsyncMock()
    return (
        patch("app.services.parse_config_service.cache_get_or_set", side_effect=_cache_passthrough),
        patch("app.services.parse_config_service.AsyncSessionLocal", _mock_session_local(session)),
        patch("app.services.parse_config_service.parse_config_repo", mock_repo),
        mock_repo,
    )


@pytest.mark.asyncio
class TestResolve:
    async def test_defaults_when_no_db_row(self):
        """无 DB 行时回落内置默认（env VLM_* 兜底）。"""
        cache_p, session_p, repo_p, _ = _patch_common(repo_row=None)
        with cache_p, session_p, repo_p:
            cfg = await ParseConfigService.resolve()

        assert cfg["vlm_model"]  # 默认 qwen3-vl-flash 或 env 覆盖
        assert cfg["vlm_base_url"]
        assert cfg["vlm_detail_level"] == "high"
        assert cfg["vlm_max_tokens"] == 4096

    async def test_db_row_overrides_and_decrypts_api_key(self):
        """DB 非 NULL 字段覆盖默认；vlm_api_key 解密后返回。"""
        row = _make_row(
            vlm_model="qwen3-vl-plus",
            vlm_max_tokens=8192,
            vlm_detail_level="low",
            vlm_api_key=encrypt_api_key("sk-1234567890abcd"),
        )
        cache_p, session_p, repo_p, _ = _patch_common(repo_row=row)
        with cache_p, session_p, repo_p:
            cfg = await ParseConfigService.resolve()

        assert cfg["vlm_model"] == "qwen3-vl-plus"
        assert cfg["vlm_max_tokens"] == 8192
        assert cfg["vlm_detail_level"] == "low"
        assert cfg["vlm_api_key"] == "sk-1234567890abcd"

    async def test_resolve_vlm_for_strategy_key_mapping(self):
        """注入 strategy.vlm_config 的键名映射：model/base_url/api_key/detail/max_tokens。"""
        row = _make_row(vlm_model="m1", vlm_max_tokens=2048)
        cache_p, session_p, repo_p, _ = _patch_common(repo_row=row)
        with cache_p, session_p, repo_p:
            vlm = await ParseConfigService.resolve_vlm_for_strategy()

        assert set(vlm.keys()) == {"model", "base_url", "api_key", "detail", "max_tokens"}
        assert vlm["model"] == "m1"
        assert vlm["max_tokens"] == 2048


class TestMaskApiKey:
    def test_empty_key(self):
        assert _mask_api_key("") == ""

    def test_short_key_fully_masked(self):
        assert _mask_api_key("short") == "****"
        assert _mask_api_key("12345678") == "****"

    def test_long_key_head_tail(self):
        assert _mask_api_key("sk-1234567890abcd") == "sk-1****abcd"


@pytest.mark.asyncio
class TestGetForApi:
    async def test_masked_and_configured_flag(self):
        """api_key 掩码回显，不明文外发。"""
        row = _make_row(vlm_api_key=encrypt_api_key("sk-1234567890abcd"))
        cache_p, session_p, repo_p, _ = _patch_common(repo_row=row)
        with cache_p, session_p, repo_p:
            data = await ParseConfigService.get_for_api()

        assert data["vlm_api_key_configured"] is True
        assert data["vlm_api_key_masked"] == "sk-1****abcd"
        assert "vlm_api_key" not in data

    async def test_unconfigured_when_no_key(self):
        cache_p, session_p, repo_p, _ = _patch_common(repo_row=None)
        with cache_p, session_p, repo_p, \
             patch("app.services.parse_config_service.settings") as mock_settings:
            mock_settings.VLM_MODEL = "qwen3-vl-flash"
            mock_settings.VLM_API_BASE = "https://example.com/v1"
            mock_settings.VLM_API_KEY = ""
            mock_settings.VLM_DETAIL_LEVEL = "high"
            data = await ParseConfigService.get_for_api()

        assert data["vlm_api_key_configured"] is False
        assert data["vlm_api_key_masked"] == ""


@pytest.mark.asyncio
class TestSave:
    async def test_save_without_api_key_keeps_existing(self):
        """vlm_api_key 留空时保持既有加密值不变。"""
        existing = _make_row(vlm_api_key=encrypt_api_key("sk-old-key-0000"))
        cache_p, session_p, repo_p, mock_repo = _patch_common(repo_row=existing)
        with cache_p, session_p, repo_p, \
             patch("app.services.parse_config_service.cache_delete", new=AsyncMock()):
            await ParseConfigService.save({
                "vlm_model": "qwen3-vl-flash",
                "vlm_base_url": "https://example.com/v1",
                "vlm_api_key": "",  # 留空
                "vlm_detail_level": "high",
                "vlm_max_tokens": 4096,
            })

        mock_repo.upsert.assert_awaited_once()
        saved = mock_repo.upsert.call_args.args[1]
        assert decrypt_api_key(saved.vlm_api_key) == "sk-old-key-0000"

    async def test_save_with_api_key_encrypts(self):
        """新 api_key 加密存储，且可解密回原值。"""
        cache_p, session_p, repo_p, mock_repo = _patch_common(repo_row=None)
        with cache_p, session_p, repo_p, \
             patch("app.services.parse_config_service.cache_delete", new=AsyncMock()):
            await ParseConfigService.save({
                "vlm_model": "qwen3-vl-flash",
                "vlm_base_url": "https://example.com/v1",
                "vlm_api_key": "sk-newkey12345",
                "vlm_detail_level": "high",
                "vlm_max_tokens": 4096,
            })

        saved = mock_repo.upsert.call_args.args[1]
        # 无论是否配置 Fernet（未配置时开发环境原样返回），都能解密回原值
        assert decrypt_api_key(saved.vlm_api_key) == "sk-newkey12345"
