"""Shared fixtures for the runtime/harness test tree.

Loaded automatically by pytest for tests under ``runtime/harness/``.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from yoke_core.domain.project_scratch_dir import hook_marker_path
from runtime.api.fixtures.file_test_db import init_test_db
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from runtime.harness import hook_helpers, hook_helpers_markers

from yoke_core.domain import db_backend as _db_backend

os.environ.setdefault(_db_backend.TEST_TRACK_CONNECTIONS_ENV, "1")
if not (
    os.environ.get(_db_backend.PG_DSN_ENV)
    or os.environ.get(_db_backend.PG_DSN_FILE_ENV)
):
    from yoke_core.tools import pg_testcluster as _pg_testcluster

    _pg_rc = _pg_testcluster.ensure_started()
    if _pg_rc != 0:
        raise RuntimeError(
            "failed to start local Postgres test cluster; run "
            "`python3 -m yoke_core.tools.pg_testcluster start` for details"
        )
    os.environ[_db_backend.PG_DSN_ENV] = _pg_testcluster.dsn()


@pytest.fixture(autouse=True)
def clean_markers(tmp_path, monkeypatch):
    """Isolate marker files per test via a tmp-rooted YOKE_SCRATCH_ROOT.

    The module-level CURRENT_ITEM_MARKER / DONE_ITEM_MARKER constants
    are computed at import time from the ambient scratch root, so under
    pytest-xdist they collide across workers. Per-test isolation: point
    YOKE_SCRATCH_ROOT at tmp_path and recompute the constants for the
    duration of the test.
    """
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
    current_path = str(hook_marker_path("current-item"))
    done_path = str(hook_marker_path("done-item"))
    monkeypatch.setattr(hook_helpers_markers, "CURRENT_ITEM_MARKER", current_path)
    monkeypatch.setattr(hook_helpers_markers, "DONE_ITEM_MARKER", done_path)
    monkeypatch.setattr(hook_helpers, "CURRENT_ITEM_MARKER", current_path)
    monkeypatch.setattr(hook_helpers, "DONE_ITEM_MARKER", done_path)
    yield


@pytest.fixture(autouse=True)
def _harness_event_isolation(monkeypatch):
    """Pin ``YOKE_EVENTS_ISOLATION=1`` for every harness test.

    Defense-in-depth parity with
    ``runtime.api.fixtures.runtime._yoke_event_isolation``. The harness
    subtree has its own pytest conftest, so the API-side autouse does not
    apply here. Without this fixture, a harness test that accidentally walks
    an emit path with a real Postgres authority would write to the live
    ledger; the gate makes refusal happen at envelope build time (the
    emitter returns ``isolation_gate_refused`` before any DB write).
    """
    monkeypatch.setenv("YOKE_EVENTS_ISOLATION", "1")
    yield


@pytest.fixture(autouse=True)
def _no_batch_connection(monkeypatch):
    """Pin the telemetry flush to its no-shared-connection path.

    The batched flush opens one connection and severity-filters sub-floor rows.
    Whether a connection is available in a bare unit run is environmental, so
    dispatch/emission tests would non-deterministically see filtered-out
    guardrail rows. Forcing the no-connection path makes per-module emission
    deterministic. Tests that exercise the filter itself (the skip-throwaway
    test) override this by setting their own ``hook_emit_connection`` in the
    test body — the later setattr wins.
    """
    from contextlib import contextmanager

    @contextmanager
    def _none():
        yield None

    monkeypatch.setattr("yoke_core.domain.events_writes.hook_emit_connection", _none)
    yield


@pytest.fixture
def dispatch_db(tmp_path):
    """Create a DB with epic_dispatch_chains and items tables."""
    from yoke_core.domain import db_backend

    def _apply_schema() -> None:
        conn = db_backend.connect()
        try:
            apply_fixture_ddl(conn, """
        CREATE TABLE epic_dispatch_chains (
            epic_id INTEGER,
            worktree_path TEXT,
            current_task TEXT
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            title TEXT,
            type TEXT DEFAULT 'issue',
            status TEXT DEFAULT 'implementing',
            worktree TEXT
        );
    """)
        finally:
            conn.close()

    with init_test_db(tmp_path, apply_schema=_apply_schema) as db_path:
        yield db_path


@pytest.fixture
def no_parent_argv():
    """Stub parent-argv reading so env-only tests aren't affected by the real PPID.

    Without this, ``detect_model`` under Claude Code would actually shell out
    to ``ps -p $PPID`` and could pick up a ``--model`` flag from the test
    runner's parent, masking the behavior under test.
    """
    with mock.patch("runtime.harness.hook_helpers._read_parent_argv", return_value=[]):
        yield
