"""Pytest configuration and shared fixtures."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

# 设置默认的异步事件循环策略（Windows 上避免 ProactorEventLoop 警告）
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_session():
    """返回一个可复用的 mock async session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture
def mock_user():
    """返回一个标准 mock 用户对象."""
    user = MagicMock()
    user.id = "user-test-001"
    user.username = "testuser"
    user.password_hash = "$pbkdf2-sha256$29000$..."  # 占位
    user.email = "test@example.com"
    user.phone = None
    user.avatar_url = None
    user.role = "user"
    user.status = "active"
    user.llm_config = {}
    user.token_quota_monthly = 1_000_000
    user.token_used_monthly = 0
    user.token_reset_at = None
    user.created_at = None
    user.updated_at = None
    return user


@pytest.fixture
def mock_admin():
    """返回一个标准 mock admin 用户对象."""
    user = MagicMock()
    user.id = "user-admin-001"
    user.username = "admin"
    user.password_hash = "$pbkdf2-sha256$29000$..."
    user.email = "admin@example.com"
    user.phone = None
    user.avatar_url = None
    user.role = "admin"
    user.status = "active"
    user.llm_config = {}
    user.token_quota_monthly = 10_000_000
    user.token_used_monthly = 0
    user.token_reset_at = None
    user.created_at = None
    user.updated_at = None
    return user
