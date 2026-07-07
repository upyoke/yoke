"""Helpers for :mod:`runtime.api.test_routed_ownership_release_gap`.

Split out so the regression test file stays within the AGENTS.md file
budget. Owns the minimal per-test schema build, session/item seeding, and
the incident timeline assembly. The release intent rides on
``work_claims.release_reason_intent`` — stamped by the production release
helper itself — so no event seeding is required.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Any, Optional

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.sessions_lifecycle_release import (
    release_work_claim_for_execution,
)
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.work_claim_targets import make_item_target
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from runtime.api.scheduler_test_fixtures import (
    EVENTS_SCHEMA,
    HARNESS_SESSIONS_SCHEMA,
    PATH_CLAIMS_SCHEMA,
    WORK_CLAIMS_SCHEMA,
)
from runtime.api.test_dependency_schema import (
    ITEMS_SCHEMA,
    ITEM_DEPENDENCIES_SCHEMA,
    PROJECTS_SCHEMA,
)
from runtime.api.test_constants import TEST_MODEL_ID


# Synthetic item id — high enough that no live backlog item collides.
SYNTHETIC_ITEM_ID = 9999
SYNTHETIC_ITEM_REF = f"YOK-{SYNTHETIC_ITEM_ID}"

# Real incident session ids. They are session identifiers, not
# drifting ticket ids, so they are safe as literals.
SESSION_A = "019e1f0d-7f82-72d2-85ee-b46947b2a6fd"
SESSION_B = "019e1f0a-a6a2-7321-835f-9772a881820b"

WORKSPACE = "/tmp/yok1674-routed-ownership-fixture"
_SEED_TS = "2026-05-13T01:58:26+00:00"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def apply_release_gap_schema() -> None:
    """``init_test_db`` ``apply_schema`` strategy for the release-gap family.

    Builds the minimal scheduler-input table set (items, item_dependencies,
    harness_sessions, work_claims, events) the routed-ownership defense reads —
    deliberately NOT the full production schema. Resolves its own connection
    through the backend factory with ``YOKE_PG_DSN`` repointed to the
    disposable per-test Postgres database, so each test gets an isolated table
    set that never collides with the ambient production relations.
    """
    conn = db_backend.connect()
    try:
        apply_fixture_ddl(
            conn,
            ITEMS_SCHEMA
            + ITEM_DEPENDENCIES_SCHEMA
            + PROJECTS_SCHEMA
            + HARNESS_SESSIONS_SCHEMA
            + WORK_CLAIMS_SCHEMA
            + EVENTS_SCHEMA
            + PATH_CLAIMS_SCHEMA,
        )
        conn.commit()
    finally:
        conn.close()


def make_db(path: str):
    """Backend-aware connection to a :func:`init_test_db` release-gap database."""
    return connect_test_db(path)


def seed_item(conn: Any) -> None:
    """Insert the synthetic routed item in a frontier-runnable status."""
    spec = "# Routed item under test\n\nSynthetic fixture row."
    p = _p(conn)
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, project_id, "
        "project_sequence, created_at, updated_at, source, frozen, spec) "
        f"VALUES ({p}, {p}, 'issue', 'refined-idea', 'high', 1, "
        f"{p}, {p}, {p}, 'user', 0, {p})",
        (SYNTHETIC_ITEM_ID, "Routed item under test", SYNTHETIC_ITEM_ID,
         _SEED_TS, _SEED_TS, spec),
    )
    conn.commit()


def register_live_session(
    conn: Any,
    session_id: str,
    *,
    current_item_id: Optional[str] = None,
) -> None:
    """Insert a live ``harness_sessions`` row with a fresh heartbeat.

    Avoids :func:`register_session` so the test does not depend on the
    canonical actor-resolution path (which reaches into config tables
    this minimal fixture does not provision).
    """
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    p = _p(conn)
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, execution_lane, "
        " capabilities, workspace, mode, offered_at, last_heartbeat, "
        " ended_at, offer_envelope, current_item_id, "
        " current_item_set_at) "
        f"VALUES ({p}, 'claude-code', 'anthropic', '{TEST_MODEL_ID}', "
        f" 'primary', '[]', {p}, 'wait', {p}, {p}, NULL, NULL, {p}, {p})",
        (
            session_id, WORKSPACE, now, now,
            current_item_id, now if current_item_id else None,
        ),
    )
    conn.commit()


def release_with_non_terminal_intent(
    conn: Any, session_id: str, item_id: int,
) -> None:
    """Run the production release helper with an incident intent.

    The non-terminal intent ``readiness-check-blocked`` is stamped on
    ``work_claims.release_reason_intent`` by the helper itself. The
    DB-stored canonical ``release_reason`` is ``released`` — that
    collapse is exactly the gap the defense must close.
    """
    target = make_item_target(item_id)
    result = release_work_claim_for_execution(
        conn, session_id, target, "readiness-check-blocked",
    )
    assert result["released"] is True, (
        f"release_work_claim_for_execution should succeed; got {result!r}"
    )
    assert result["reason_intent"] == "readiness-check-blocked"
    assert result["reason_stored"] == "released"


def build_release_gap_fixture(conn: Any) -> None:
    """Seed the timeline: session A claims and non-terminal-releases."""
    seed_item(conn)
    register_live_session(
        conn, SESSION_A, current_item_id=str(SYNTHETIC_ITEM_ID),
    )
    register_live_session(conn, SESSION_B)
    claim_work(conn, session_id=SESSION_A, item_id=SYNTHETIC_ITEM_REF)
    p = _p(conn)
    claim_id_row = conn.execute(
        f"SELECT id FROM work_claims WHERE session_id = {p} AND item_id = {p} "
        "AND released_at IS NULL",
        (SESSION_A, SYNTHETIC_ITEM_ID),
    ).fetchone()
    assert claim_id_row is not None, "session A's live claim row should exist"
    release_with_non_terminal_intent(conn, SESSION_A, SYNTHETIC_ITEM_ID)


class _ReleaseGapDbCase(unittest.TestCase):
    """Base providing a backend-aware per-test release-gap DB.

    The autouse fixture owns the disposable per-test Postgres database lifecycle.
    Subclass tests call :meth:`make_db` for a backend-aware connection to it.
    Lives here so the regression test file stays within the AGENTS.md file
    budget.
    """

    @pytest.fixture(autouse=True)
    def _release_gap_db(self, tmp_path):
        with init_test_db(
            tmp_path, apply_schema=apply_release_gap_schema,
        ) as db_path:
            self._db_path = db_path
            yield

    def make_db(self):
        """Backend-aware connection to this test's release-gap DB."""
        return make_db(self._db_path)


__all__ = [
    "SYNTHETIC_ITEM_ID",
    "SYNTHETIC_ITEM_REF",
    "SESSION_A",
    "SESSION_B",
    "WORKSPACE",
    "apply_release_gap_schema",
    "make_db",
    "seed_item",
    "register_live_session",
    "release_with_non_terminal_intent",
    "build_release_gap_fixture",
    "_ReleaseGapDbCase",
]
