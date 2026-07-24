"""Tests for authentication endpoints."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.api.auth import hash_password


@pytest.mark.asyncio
class TestAuth:
    async def test_register_success(self):
        """测试用户注册成功."""
        with patch("app.api.auth.user_repo") as mock_repo:
            mock_repo.get_by_username = AsyncMock(return_value=None)
            mock_repo.create = AsyncMock()

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/v1/auth/register", json={
                    "username": "newuser",
                    "password": "password123",
                    "email": "new@example.com",
                })

            assert resp.status_code == 200
            data = resp.json()
            assert data["code"] == 0
            assert "user_id" in data["data"]
            assert data["data"]["username"] == "newuser"

    async def test_register_duplicate_username(self):
        """测试重复用户名注册失败."""
        existing_user = MagicMock()
        existing_user.id = "user-existing"

        with patch("app.api.auth.user_repo") as mock_repo:
            mock_repo.get_by_username = AsyncMock(return_value=existing_user)

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/v1/auth/register", json={
                    "username": "existing",
                    "password": "password123",
                })

            assert resp.status_code == 400
            assert resp.json()["detail"] == "Username already exists"

    async def test_login_success(self):
        """测试登录成功并返回 token."""
        user = MagicMock()
        user.id = "user-001"
        user.username = "testuser"
        user.password_hash = hash_password("secret123")
        user.role = "user"
        user.status = "active"

        with patch("app.api.auth.user_repo") as mock_repo:
            mock_repo.get_by_username = AsyncMock(return_value=user)

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/v1/auth/login", json={
                    "username": "testuser",
                    "password": "secret123",
                })

            assert resp.status_code == 200
            data = resp.json()
            assert data["code"] == 0
            assert "access_token" in data["data"]
            assert data["data"]["expires_in"] > 0

    async def test_login_wrong_password(self):
        """测试密码错误返回 401."""
        user = MagicMock()
        user.id = "user-001"
        user.username = "testuser"
        user.password_hash = hash_password("secret123")
        user.role = "user"
        user.status = "active"

        with patch("app.api.auth.user_repo") as mock_repo:
            mock_repo.get_by_username = AsyncMock(return_value=user)

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/v1/auth/login", json={
                    "username": "testuser",
                    "password": "wrongpassword",
                })

            assert resp.status_code == 401
            assert resp.json()["detail"] == "Invalid username or password"

    async def test_get_me_without_token(self):
        """测试未携带 token 访问 /me 返回 401."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/auth/me")

        assert resp.status_code == 401
