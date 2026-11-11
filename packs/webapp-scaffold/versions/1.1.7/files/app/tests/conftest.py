"""Shared test fixtures for {{project_display_name}} test suite.

Provides:
- Temporary SQLite DB with schema applied
- Seeded DB (org, user)
- APP_DB_PATH env var override for all tests
"""

import hashlib
import json
import os
import sqlite3
import sys

import pytest

# Ensure the app root is importable
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)


ARTIFACT_VERIFICATION_RECEIPT_SHA256 = "f" * 64
SOURCE_COMMIT = "b" * 40
SOURCE_SHA256 = "a" * 64


def verified_artifact_receipt(manifest):
    """Test double for a project adapter that verified signed evidence."""
    artifact = manifest["artifact"]
    return {
        "verifier": "test-signed-release-evidence",
        "source_artifact": artifact["source_artifact"],
        "source_sha256": artifact["source_sha256"],
        "source_commit": artifact["source_commit"],
        "manifest_sha256": manifest["manifest_sha256"],
        "verification_receipt_sha256": ARTIFACT_VERIFICATION_RECEIPT_SHA256,
    }


def write_adoption_manifest(
    path,
    entries,
    *,
    engine_version="1.0.0",
    source_artifact="sample-app-1.0.0",
    source_commit=SOURCE_COMMIT,
    source_sha256=SOURCE_SHA256,
):
    """Write the canonical test artifact manifest and return its pinned hash."""
    payload = {
        "schema_version": 1,
        "artifact": {
            "engine_version": engine_version,
            "source_artifact": source_artifact,
            "source_sha256": source_sha256,
            "source_commit": source_commit,
        },
        "entries": [
            {"name": name, "content_sha256": digest} for name, digest in entries.items()
        ],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    path.write_text(
        json.dumps({**payload, "manifest_sha256": digest}),
        encoding="utf-8",
    )
    return path, digest


def adoption_arguments(
    manifest_sha256,
    *,
    source_commit=SOURCE_COMMIT,
    source_sha256=SOURCE_SHA256,
    adopted_by="test-operator",
):
    """Trusted inputs supplied by the test project release adapter."""
    return {
        "source_commit": source_commit,
        "source_sha256": source_sha256,
        "manifest_sha256": manifest_sha256,
        "adopted_by": adopted_by,
        "adoption_artifact_verifier": verified_artifact_receipt,
    }


# ---------------------------------------------------------------------------
# Schema helper
# ---------------------------------------------------------------------------


def _apply_schema(conn):
    """Read schema.sql and execute it against the connection."""
    schema_path = os.path.join(APP_DIR, "db", "schema.sql")
    with open(schema_path, "r") as f:
        schema_sql = f.read()
    conn.executescript(schema_sql)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary DB file path and set APP_DB_PATH env var."""
    path = str(tmp_path / "test_app.db")
    old = os.environ.get("APP_DB_PATH")
    os.environ["APP_DB_PATH"] = path
    yield path
    if old is None:
        os.environ.pop("APP_DB_PATH", None)
    else:
        os.environ["APP_DB_PATH"] = old


@pytest.fixture
def empty_db(db_path):
    """DB with schema applied but no data."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    _apply_schema(conn)
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Auth test helpers
# ---------------------------------------------------------------------------

TEST_USER_EMAIL = "test@example.com"
TEST_USER_PASSWORD = "testpassword123"
TEST_USER_NAME = "Test User"


def insert_test_user(
    conn,
    email=TEST_USER_EMAIL,
    password=TEST_USER_PASSWORD,
    name=TEST_USER_NAME,
    role="superadmin",
    api_key=None,
):
    """Insert a test user with hashed password. Returns user_id."""
    from api.auth import hash_password

    cursor = conn.execute(
        "INSERT INTO users (email, password_hash, name, role, api_key) VALUES (?, ?, ?, ?, ?)",
        (email, hash_password(password), name, role, api_key),
    )
    conn.commit()
    return cursor.lastrowid


def insert_test_org(conn, name="TestOrg", slug="testorg"):
    """Insert a test org. Returns org_id."""
    cursor = conn.execute(
        "INSERT INTO orgs (name, slug) VALUES (?, ?)",
        (name, slug),
    )
    conn.commit()
    return cursor.lastrowid


def insert_org_member(conn, org_id, user_id, role="owner"):
    """Insert an org membership."""
    conn.execute(
        "INSERT INTO org_members (org_id, user_id, role) VALUES (?, ?, ?)",
        (org_id, user_id, role),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Auth-enabled API test helpers
# ---------------------------------------------------------------------------


def setup_api_auth(path):
    """Create test user/org in the DB.

    Call AFTER schema is applied but BEFORE tests run.
    Returns (user_id, org_id).
    """
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    user_id = insert_test_user(conn)
    org_id = insert_test_org(conn)
    insert_org_member(conn, org_id, user_id)
    conn.close()
    return user_id, org_id


async def login(client):
    """Log in the test user via cookie session. Use inside async with AsyncClient."""
    resp = await client.post(
        "/api/auth/login",
        json={
            "email": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD,
        },
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
