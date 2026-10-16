"""Recorded local operator authority checks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain.local_operating_actor import (
    OPERATING_ACTOR_GRANT_REPAIR,
)
from yoke_core.domain.session_actor_binding_write import persist_operating_actor
from yoke_core.engines.doctor_hc_session_actor_binding import (
    AUTHORITY_SLUG,
    AUTHORITY_TITLE,
    hc_local_operating_actor_authority,
)

from runtime.api.fixtures.machine_config_test import select_machine_config_file


@dataclass
class _DoctorArgsStub:
    project: str = "yoke"
    fix: bool = False


@dataclass
class _Record:
    slug: str
    label: str
    verdict: str
    detail: str


class _RecorderStub:
    def __init__(self) -> None:
        self.records: List[_Record] = []

    def record(self, slug: str, label: str, verdict: str, detail: str) -> None:
        self.records.append(_Record(slug, label, verdict, detail))


SCHEMA = """
CREATE TABLE projects (
    id SERIAL PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ
);
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    actor_id INTEGER,
    ended_at TIMESTAMPTZ
);
CREATE TABLE actors (status TEXT NOT NULL DEFAULT 'active',
    id SERIAL PRIMARY KEY,
    kind TEXT NOT NULL,
    system_component TEXT,
    name TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE organizations (
    id SERIAL PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    domain TEXT DEFAULT NULL,
    settings TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL
);
INSERT INTO organizations (slug, name, created_at)
    VALUES ('default', 'Default', '2026-05-01T00:00:00Z');
"""

ENV = "local"


@pytest.fixture(autouse=True)
def machine_config(tmp_path, monkeypatch):
    """A throwaway machine config, so no test reads the operator's own."""
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "active_env": ENV,
                "connections": {ENV: {"transport": "local-postgres"}},
            }
        ),
        encoding="utf-8",
    )
    select_machine_config_file(monkeypatch, str(path))
    return path


@pytest.fixture
def conn():
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    apply_fixture_ddl(c, SCHEMA)
    yield c
    c.close()
    pg_testdb.drop_test_database(name)


def _bind(conn, actor_id: int) -> None:
    persist_operating_actor(conn, actor_id, env=ENV)


def _seed_human(conn) -> int:
    row = conn.execute(
        "INSERT INTO actors (kind, created_at) "
        "VALUES ('human', '2026-05-01T00:00:00Z') RETURNING id"
    ).fetchone()
    conn.commit()
    return int(row[0])


def _run_authority(conn, *, fix: bool = False) -> _Record:
    rec = _RecorderStub()
    hc_local_operating_actor_authority(conn, _DoctorArgsStub(fix=fix), rec)
    assert len(rec.records) == 1
    record = rec.records[0]
    assert record.slug == AUTHORITY_SLUG and record.label == AUTHORITY_TITLE
    return record


def _auth_schema(conn) -> None:
    """Build the org/role tables a real universe carries."""
    from yoke_core.domain.auth_schema import create_auth_tables
    from yoke_core.domain.org_schema import create_org_tables

    create_auth_tables(conn)
    create_org_tables(conn)
    conn.commit()


def test_authority_skips_a_universe_without_the_org_tables(conn):
    _seed_human(conn)
    assert _run_authority(conn).verdict == "PASS"


def test_authority_fails_when_the_operating_actor_holds_no_role(conn):
    _auth_schema(conn)
    actor_id = _seed_human(conn)
    _bind(conn, actor_id)
    record = _run_authority(conn)
    assert record.verdict == "FAIL"
    assert OPERATING_ACTOR_GRANT_REPAIR in record.detail


def test_authority_fix_grants_the_org_admin_role(conn):
    _auth_schema(conn)
    actor_id = _seed_human(conn)
    _bind(conn, actor_id)
    record = _run_authority(conn, fix=True)
    assert record.verdict == "PASS"
    granted = conn.execute(
        "SELECT COUNT(*) FROM actor_org_roles aor JOIN roles r ON r.id = aor.role_id "
        "WHERE aor.actor_id = %s AND r.name = 'admin'",
        (actor_id,),
    ).fetchone()[0]
    assert granted == 1


def test_authority_passes_once_the_grant_exists(conn):
    _auth_schema(conn)
    actor_id = _seed_human(conn)
    _bind(conn, actor_id)
    _run_authority(conn, fix=True)
    assert _run_authority(conn).verdict == "PASS"
