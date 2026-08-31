"""HC-session-actor-binding coverage.

The check exists for rows written before registration bound an actor:
they look healthy until the session tries to register a path claim,
which refuses with no hint about where the NULL came from. So the check
reads those rows directly, and ``--fix`` binds them to the actor that
operates the universe — the same resolver registration uses.

When no operating actor can be resolved the check reports that reason
rather than inventing an identity, because binding the wrong human is
worse than naming the ambiguity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain.local_operating_actor import (
    OPERATING_ACTOR_GRANT_REPAIR,
)
from yoke_core.engines.doctor_hc_session_actor_binding import (
    AUTHORITY_SLUG,
    AUTHORITY_TITLE,
    SLUG,
    TITLE,
    hc_local_operating_actor_authority,
    hc_session_actor_binding,
)


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
    created_at TEXT
);
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    actor_id INTEGER,
    ended_at TEXT
);
CREATE TABLE actors (
    id SERIAL PRIMARY KEY,
    kind TEXT NOT NULL,
    system_component TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE actor_labels (
    id SERIAL PRIMARY KEY,
    actor_id INTEGER NOT NULL,
    surface TEXT NOT NULL,
    label TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


@pytest.fixture
def conn():
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    apply_fixture_ddl(c, SCHEMA)
    yield c
    c.close()
    pg_testdb.drop_test_database(name)


def _seed_human(conn) -> int:
    row = conn.execute(
        "INSERT INTO actors (kind, created_at) "
        "VALUES ('human', '2026-05-01T00:00:00Z') RETURNING id"
    ).fetchone()
    conn.commit()
    return int(row[0])


def _insert_session(conn, session_id: str, actor_id: int | None) -> None:
    conn.execute(
        "INSERT INTO harness_sessions (session_id, actor_id) VALUES (%s, %s)",
        (session_id, actor_id),
    )
    conn.commit()


def _run(conn, *, fix: bool = False) -> _Record:
    rec = _RecorderStub()
    hc_session_actor_binding(conn, _DoctorArgsStub(fix=fix), rec)
    assert len(rec.records) == 1
    record = rec.records[0]
    assert record.slug == SLUG and record.label == TITLE
    return record


def test_passes_when_every_session_names_an_actor(conn):
    actor_id = _seed_human(conn)
    _insert_session(conn, "bound", actor_id)
    assert _run(conn).verdict == "PASS"


def test_fails_and_names_the_repair_for_actorless_sessions(conn):
    _seed_human(conn)
    _insert_session(conn, "unbound", None)
    record = _run(conn)
    assert record.verdict == "FAIL"
    assert "unbound" in record.detail
    assert OPERATING_ACTOR_GRANT_REPAIR in record.detail


def test_fix_binds_actorless_sessions_to_the_operating_actor(conn):
    actor_id = _seed_human(conn)
    _insert_session(conn, "unbound-one", None)
    _insert_session(conn, "unbound-two", None)
    record = _run(conn, fix=True)
    assert record.verdict == "PASS"
    bound = conn.execute(
        "SELECT COUNT(*) FROM harness_sessions WHERE actor_id = %s",
        (actor_id,),
    ).fetchone()[0]
    assert bound == 2


def test_reports_the_resolver_reason_when_no_operating_actor_exists(conn):
    _insert_session(conn, "unbound", None)
    record = _run(conn, fix=True)
    assert record.verdict == "FAIL"
    assert "yoke onboard" in record.detail
    still_null = conn.execute(
        "SELECT COUNT(*) FROM harness_sessions WHERE actor_id IS NULL"
    ).fetchone()[0]
    assert still_null == 1


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
    _seed_human(conn)
    record = _run_authority(conn)
    assert record.verdict == "FAIL"
    assert OPERATING_ACTOR_GRANT_REPAIR in record.detail


def test_authority_fix_grants_the_org_admin_role(conn):
    _auth_schema(conn)
    actor_id = _seed_human(conn)
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
    _seed_human(conn)
    _run_authority(conn, fix=True)
    assert _run_authority(conn).verdict == "PASS"
