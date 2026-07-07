"""Shared pytest fixtures for Yoke API tests.

Fixtures are organized into sub-modules under ``runtime.api.fixtures``:

- ``backlog`` -- schema DDL, test_db, and insert helpers
- ``github`` -- GitHub mock fixtures
- ``runtime`` -- filesystem pollution detection and event isolation

This file registers them via ``pytest_plugins`` and re-exports commonly
used helpers so that existing ``from runtime.api.conftest import ...``
imports continue to work.
"""

from __future__ import annotations

import os

import pytest

# ---------------------------------------------------------------------------
# Import-time DB-init isolation
# ---------------------------------------------------------------------------
#
# Prevent test collection and module imports from triggering
# ``yoke_core.cli.db_router._auto_init`` or ``schema.cmd_init``
# against the canonical filesystem.  Without this guard, a plain
# ``import yoke_core.cli.db_router`` during pytest collection can
# drive ``cmd_init()`` against the newly resolved state dir (e.g.
# ``<main-root>/data/``) before the migration is deliberate.
#
# Tests that intentionally exercise auto-init opt in by:
#   1. Setting ``YOKE_DB`` to a temp path, AND
#   2. Setting ``YOKE_DB_INIT_ALLOW=1``, AND
#   3. Clearing ``YOKE_DB_INIT_DONE`` in their local setup.
#
# This runs at import time (before fixtures) so it covers collection-phase
# imports too -- a function-scoped fixture would be too late.
os.environ.setdefault("YOKE_DB_INIT_DONE", "1")

# ---------------------------------------------------------------------------
# Postgres backend: per-worker disposable ambient test database
# ---------------------------------------------------------------------------
#
# Ambient ``db_helpers.connect()`` calls must land in an isolated, schema-loaded
# test database — never a real one. Create (once per xdist worker) a per-worker
# ambient test DB, apply the canonical schema, and repoint YOKE_PG_DSN at it.
# When no explicit CI/operator DSN is bound, start the local disposable cluster
# and bind its maintenance DSN before ambient DB setup. Pytest must never fall
# through to the connected Aurora environment.

from yoke_core.domain import db_backend as _db_backend  # noqa: E402

os.environ.setdefault(_db_backend.TEST_TRACK_CONNECTIONS_ENV, "1")
if not (
    os.environ.get(_db_backend.PG_DSN_ENV)
    or os.environ.get(_db_backend.PG_DSN_FILE_ENV)
):
    from yoke_core.tools import pg_testcluster as _pg_testcluster  # noqa: E402

    _pg_rc = _pg_testcluster.ensure_started()
    if _pg_rc != 0:
        raise RuntimeError(
            "failed to start local Postgres test cluster; run "
            "`python3 -m yoke_core.tools.pg_testcluster start` for details"
        )
    os.environ[_db_backend.PG_DSN_ENV] = _pg_testcluster.dsn()
from runtime.api.fixtures.pg_testdb import setup_ambient_test_db  # noqa: E402

setup_ambient_test_db()
_AMBIENT_TEST_PG_DSN = os.environ.get(_db_backend.PG_DSN_ENV)
_AMBIENT_TEST_PG_DSN_FILE = os.environ.get(_db_backend.PG_DSN_FILE_ENV)

# ---------------------------------------------------------------------------
# Fixture sub-module registration
# ---------------------------------------------------------------------------

pytest_plugins = [
    "runtime.api.fixtures.backlog",
    "runtime.api.fixtures.github",
    "runtime.api.fixtures.runtime",
]


@pytest.fixture(autouse=True)
def _isolate_commit_cache(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Redirect the on-disk commit/activity caches to a per-test tmp dir.

    Both caches resolve their file location through
    ``machine_config.cache_dir()`` (``~/.yoke/cache`` by default). Tests
    that rebuild the board against real temp repos — e.g. the merge-worktree
    suites — otherwise write their throwaway-repo entries into the developer's
    real cache and, under xdist, race each other's writes there. That
    pollution evicted real-repo entries from the production cache. Pinning the
    cache path per test keeps every API test off the real cache file. Board
    renderer tests previously did this only under ``board/tests/``; this is the
    same isolation, broadened to all of ``runtime/api``.
    """
    from yoke_contracts.board import widgets_commit_cache as _commit_cache
    from yoke_contracts.board import activity_cache as _activity_cache

    monkeypatch.setattr(
        _commit_cache, "_cache_path",
        lambda: tmp_path / "cache" / ".commit-cache.json",
    )
    monkeypatch.setattr(
        _activity_cache, "_cache_path",
        lambda: tmp_path / "cache" / "board-activity-day-counts.json",
    )
    _commit_cache._reset_memo_for_tests()
    yield
    _commit_cache._reset_memo_for_tests()


@pytest.fixture(autouse=True)
def _block_live_github_rest_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make tests fail fast before they can hit live GitHub REST."""
    if os.environ.get("YOKE_TEST_ALLOW_LIVE_REST") != "1":
        monkeypatch.setenv("YOKE_TEST_BLOCK_LIVE_REST", "1")


@pytest.fixture(autouse=True)
def _isolate_machine_config(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin every API test to the local in-process dispatch transport.

    ``call_dispatcher`` (and every CLI adapter riding it) consults the
    machine config's active connection; on a developer machine whose
    active env declares ``transport: "https"`` (the dogfood default
    since the prod cutover), an unisolated test would relay its
    envelope to the LIVE prod API instead of in-process dispatch — so
    dispatch-stub assertions fail only after a real network attempt.
    Pointing ``YOKE_MACHINE_HOME`` at an empty per-test dir makes
    ``machine_config.load_config`` return ``{}`` so transport
    resolution falls back to local in-process dispatch, matching CI
    (which has no machine config). Tests that exercise machine-config
    behavior set their own ``YOKE_MACHINE_HOME`` / explicit config
    paths and override this default; the test-DB authority is
    unaffected (Postgres binding rides ``YOKE_PG_DSN``, not the
    machine config).
    """
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    monkeypatch.delenv("YOKE_MACHINE_CONFIG_FILE", raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)


@pytest.fixture(autouse=True)
def _ensure_test_session_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mint a synthetic ambient session id for the test process.

    The function-call dispatcher's actor-identity guard
    (``yoke_core.domain.yoke_function_actor_identity.bind_actor_identity``)
    rejects every mutating call when no ambient harness session env var is
    set. Local laptops always have one (the developer is in a Yoke
    session); CI runners have none. Tests that exercise mutating
    dispatcher paths must satisfy the contract, not bypass it — minting a
    synthetic id here keeps the dispatcher gate intact while letting CI
    runs match laptop runs.

    Tests that intentionally exercise the missing-session branch override
    this with ``monkeypatch.delenv``; pytest fixture ordering guarantees
    the local override wins.
    """
    if not any(
        os.environ.get(name)
        for name in ("YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID")
    ):
        monkeypatch.setenv("YOKE_SESSION_ID", "test-session-autouse")


@pytest.fixture(autouse=True)
def _clear_bound_workspace_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear the workspace anchor env for every API test.

    Active Yoke sessions export ``YOKE_BOUND_WORKSPACE`` from the
    SessionStart hook. The substrate renderer's reader hot path still
    consults that env via
    ``yoke_core.domain.agents_render_workspace.require_reader_root``
    as a legacy fallback, and the PreToolUse lint
    ``yoke_core.domain.lint_workspace_cwd_match`` reads it directly.
    Clearing it here keeps tests that exercise reader / writer paths
    against ``tmp_path`` from picking up the ambient session anchor;
    the writer-side work-claim authority guard
    (``yoke_core.domain.workspace_authority.assert_target_under_session_work_authority``)
    is independently gated on ``$YOKE_SESSION_ID`` so it stays
    no-op for tests with no harness session.
    """
    monkeypatch.delenv("YOKE_BOUND_WORKSPACE", raising=False)


@pytest.fixture(autouse=True)
def _close_leaked_pg_connections():
    """Restore ambient Postgres authority and close leaked native handles."""
    baseline = _db_backend.tracked_test_connection_count()
    yield
    _db_backend.close_tracked_test_connections_since(baseline)
    if _AMBIENT_TEST_PG_DSN is not None:
        os.environ[_db_backend.PG_DSN_ENV] = _AMBIENT_TEST_PG_DSN
    else:
        os.environ.pop(_db_backend.PG_DSN_ENV, None)
    if _AMBIENT_TEST_PG_DSN_FILE is not None:
        os.environ[_db_backend.PG_DSN_FILE_ENV] = _AMBIENT_TEST_PG_DSN_FILE
    else:
        os.environ.pop(_db_backend.PG_DSN_FILE_ENV, None)

# ---------------------------------------------------------------------------
# Backward-compatible re-exports
# ---------------------------------------------------------------------------
# Many test files do ``from runtime.api.conftest import SCHEMA_DDL`` etc.
# Re-export from non-plugin modules so pytest can import the backlog fixture
# plugin itself and assertion-rewrite it before collection.

from runtime.api.fixtures.backlog_inserts import (  # noqa: E402, F401
    insert_deployment_run,
    insert_epic_task,
    insert_event,
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.fixtures.schema_ddl import SCHEMA_DDL  # noqa: E402, F401
