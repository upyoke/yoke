"""Tests for auth API endpoints (login, logout, me, password change, API key management)."""

import os
import sqlite3
import sys

import pytest

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")

from httpx import AsyncClient, ASGITransport  # noqa: E402
from api.main import create_app  # noqa: E402
from tests.conftest import (  # noqa: E402
    _apply_schema,
    insert_test_user, insert_test_org, insert_org_member,
    TEST_USER_EMAIL, TEST_USER_PASSWORD, TEST_USER_NAME,
)


@pytest.fixture
def auth_api_db(tmp_path):
    """Create a temp DB with schema + test user."""
    path = str(tmp_path / "api_test.db")
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    _apply_schema(conn)

    # Insert test user + org
    user_id = insert_test_user(conn)
    org_id = insert_test_org(conn)
    insert_org_member(conn, org_id, user_id)
    conn.close()

    old = os.environ.get("APP_DB_PATH")
    os.environ["APP_DB_PATH"] = path

    yield path

    if old is None:
        os.environ.pop("APP_DB_PATH", None)
    else:
        os.environ["APP_DB_PATH"] = old


class TestLogin:
    @pytest.mark.asyncio
    async def test_login_success(self, auth_api_db):
        app = create_app(db_path=auth_api_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/auth/login", json={
                "email": TEST_USER_EMAIL,
                "password": TEST_USER_PASSWORD,
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["data"]["user"]["email"] == TEST_USER_EMAIL
            assert data["data"]["user"]["name"] == TEST_USER_NAME
            assert data["data"]["user"]["role"] == "superadmin"
            # Cookie name uses {{project_name}}_session
            assert "{{project_name}}_session" in resp.cookies

    @pytest.mark.asyncio
    async def test_login_invalid_password(self, auth_api_db):
        app = create_app(db_path=auth_api_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/auth/login", json={
                "email": TEST_USER_EMAIL,
                "password": "wrongpassword",
            })
            assert resp.status_code == 401
            assert resp.json()["detail"]["code"] == "ERR_INVALID_CREDENTIALS"

    @pytest.mark.asyncio
    async def test_login_invalid_email(self, auth_api_db):
        app = create_app(db_path=auth_api_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/auth/login", json={
                "email": "nobody@example.com",
                "password": TEST_USER_PASSWORD,
            })
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_missing_fields(self, auth_api_db):
        app = create_app(db_path=auth_api_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/auth/login", json={"email": TEST_USER_EMAIL})
            assert resp.status_code == 422  # Pydantic validation error


class TestLogout:
    @pytest.mark.asyncio
    async def test_logout_clears_session(self, auth_api_db):
        app = create_app(db_path=auth_api_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # Login first
            resp = await c.post("/api/auth/login", json={
                "email": TEST_USER_EMAIL,
                "password": TEST_USER_PASSWORD,
            })
            assert resp.status_code == 200

            # Logout
            resp = await c.post("/api/auth/logout")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

            # Session should be invalidated
            resp = await c.get("/api/auth/me")
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_logout_without_auth(self, auth_api_db):
        app = create_app(db_path=auth_api_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/auth/logout")
            assert resp.status_code == 401


class TestMe:
    @pytest.mark.asyncio
    async def test_me_returns_user(self, auth_api_db):
        app = create_app(db_path=auth_api_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # Login
            await c.post("/api/auth/login", json={
                "email": TEST_USER_EMAIL,
                "password": TEST_USER_PASSWORD,
            })

            # Me
            resp = await c.get("/api/auth/me")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            user = data["data"]["user"]
            assert user["email"] == TEST_USER_EMAIL
            assert user["name"] == TEST_USER_NAME
            assert len(user["orgs"]) == 1
            assert user["orgs"][0]["name"] == "TestOrg"
            assert user["orgs"][0]["role"] == "owner"

    @pytest.mark.asyncio
    async def test_me_without_auth(self, auth_api_db):
        app = create_app(db_path=auth_api_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/auth/me")
            assert resp.status_code == 401


class TestChangePassword:
    @pytest.mark.asyncio
    async def test_change_password_ok(self, auth_api_db):
        app = create_app(db_path=auth_api_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # Login
            await c.post("/api/auth/login", json={
                "email": TEST_USER_EMAIL,
                "password": TEST_USER_PASSWORD,
            })

            # Change password
            resp = await c.put("/api/auth/password", json={
                "current_password": TEST_USER_PASSWORD,
                "new_password": "newpassword456",
            })
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

            # Logout and login with new password
            await c.post("/api/auth/logout")
            resp = await c.post("/api/auth/login", json={
                "email": TEST_USER_EMAIL,
                "password": "newpassword456",
            })
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_change_password_wrong_current(self, auth_api_db):
        app = create_app(db_path=auth_api_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post("/api/auth/login", json={
                "email": TEST_USER_EMAIL,
                "password": TEST_USER_PASSWORD,
            })

            resp = await c.put("/api/auth/password", json={
                "current_password": "wrongpassword",
                "new_password": "newpassword456",
            })
            assert resp.status_code == 400
            assert resp.json()["detail"]["code"] == "ERR_WRONG_PASSWORD"

    @pytest.mark.asyncio
    async def test_change_password_too_short(self, auth_api_db):
        app = create_app(db_path=auth_api_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post("/api/auth/login", json={
                "email": TEST_USER_EMAIL,
                "password": TEST_USER_PASSWORD,
            })

            resp = await c.put("/api/auth/password", json={
                "current_password": TEST_USER_PASSWORD,
                "new_password": "short",
            })
            assert resp.status_code == 400
            assert resp.json()["detail"]["code"] == "ERR_WEAK_PASSWORD"


class TestApiKeyAuth:
    @pytest.mark.asyncio
    async def test_api_key_auth(self, auth_api_db):
        from api.auth import hash_password, generate_api_key
        api_key = generate_api_key()

        conn = sqlite3.connect(auth_api_db)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "INSERT INTO users (email, password_hash, name, role, api_key) VALUES (?, ?, ?, ?, ?)",
            ("apiuser@example.com", hash_password("pass"), "API User", "member", api_key),
        )
        conn.commit()
        conn.close()

        app = create_app(db_path=auth_api_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            assert resp.status_code == 200
            assert resp.json()["data"]["user"]["email"] == "apiuser@example.com"

    @pytest.mark.asyncio
    async def test_invalid_api_key(self, auth_api_db):
        app = create_app(db_path=auth_api_db)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(
                "/api/auth/me",
                headers={"Authorization": "Bearer invalid_key"},
            )
            assert resp.status_code == 401
