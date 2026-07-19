"""Tests for the {{project_display_name}} API health endpoint."""

import os
import sys

import pytest

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")

from httpx import AsyncClient, ASGITransport  # noqa: E402
from api.main import create_app  # noqa: E402
from tests.conftest import _apply_schema  # noqa: E402


@pytest.fixture
def api_db(tmp_path):
    """Create a temp DB and point APP_DB_PATH at it."""
    import sqlite3
    path = str(tmp_path / "api_test.db")
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    _apply_schema(conn)
    conn.close()

    old = os.environ.get("APP_DB_PATH")
    os.environ["APP_DB_PATH"] = path
    yield path
    if old is None:
        os.environ.pop("APP_DB_PATH", None)
    else:
        os.environ["APP_DB_PATH"] = old


@pytest.fixture
def bad_db_path(tmp_path):
    """Point APP_DB_PATH at a non-existent path."""
    path = str(tmp_path / "nonexistent" / "missing.db")
    old = os.environ.get("APP_DB_PATH")
    os.environ["APP_DB_PATH"] = path
    yield path
    if old is None:
        os.environ.pop("APP_DB_PATH", None)
    else:
        os.environ["APP_DB_PATH"] = old


@pytest.mark.asyncio
async def test_health_ok(api_db):
    """Health endpoint returns ok with valid DB."""
    app = create_app(db_path=api_db)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["data"]["db_ok"] is True
    assert data["data"]["version"] == "0.1.0"
    assert "schema_version" in data["data"]


@pytest.mark.asyncio
async def test_health_db_missing(bad_db_path):
    """Health endpoint reports db_ok=false when DB is unreachable."""
    app = create_app(db_path=bad_db_path)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["data"]["db_ok"] is False


@pytest.mark.asyncio
async def test_health_no_auth_required(api_db):
    """Health endpoint does not require authentication."""
    app = create_app(db_path=api_db)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # No cookies or auth headers
        resp = await client.get("/api/health")

    assert resp.status_code == 200
