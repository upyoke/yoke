"""Shared fixtures and helpers for backlog test suite.

Test classes are split across child modules:
  - test_backlog_mutations_*: DB helpers, execute_create, execute_update, execute_close
  - test_backlog_queries.py: dedup_search, next_display_id, dep reconciliation,
    batch update, structured write, CLI entry point

This module provides the shared tmp_db fixture and seed helpers used by the
child modules via Python import.
"""

from __future__ import annotations

from unittest import mock

import pytest

from runtime.api.conftest import insert_item
from yoke_core.domain import backlog_rendering
from yoke_core.domain import backlog_updates
from yoke_core.domain import db_backend
from yoke_core.domain.items_constants import DEFAULT_ITEM_ACTOR_ID
from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _apply_backlog_fixture_schema() -> None:
    """``apply_schema`` strategy: fixture ``SCHEMA_DDL`` + canonical actors.

    The backlog ``tmp_db`` file fixture applies ``SCHEMA_DDL`` and then seeds
    the canonical yoke-core + local human actors so writer tests resolve the
    default actor. :func:`apply_fixture_schema_ddl` reproduces the DDL apply
    (installing the Postgres introspection shims); the canonical actor seed
    then runs on a fresh backend connection so the same post-init shape lands
    on both engines.
    """
    from runtime.api.fixtures.backlog import seed_test_canonical_actors
    from yoke_core.domain.project_seed_test_helpers import seed_project_identities

    apply_fixture_schema_ddl()
    conn = db_backend.connect()
    try:
        seed_project_identities(conn)
        seed_test_canonical_actors(conn)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def tmp_db(tmp_path):
    """Backend-aware temp DB with full schema and canonical actors.

    SQLite: a real file under ``tmp_path``. Postgres: a disposable per-test
    database with ``YOKE_PG_DSN`` repointed for the fixture's lifetime. Both
    apply the fixture ``SCHEMA_DDL`` and seed the canonical actors.
    """
    with init_test_db(tmp_path, apply_schema=_apply_backlog_fixture_schema) as path:
        yield path


def _conn(path):
    """Open a backend-aware connection to the temp DB."""
    return connect_test_db(path)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_item(path, **kwargs):
    """Insert an item into the temp DB."""
    conn = _conn(path)
    insert_item(conn, **kwargs)
    conn.close()


def _seed_session(path, session_id="sess-1"):
    """Insert an active harness session for attribution tests."""
    conn = _conn(path)
    p = _p(conn)
    conn.execute(
        f"""
        INSERT INTO harness_sessions
          (session_id, executor, provider, model, execution_lane, capabilities, workspace, mode, offered_at, last_heartbeat)
        VALUES
          ({p}, 'codex', 'openai', 'test-model', 'primary', '[]', '/tmp/test', 'test', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """,
        (session_id,),
    )
    conn.commit()
    conn.close()


def _seed_claim(path, session_id="sess-1", item_id="10"):
    """Insert an active exclusive claim for a session."""
    conn = _conn(path)
    p = _p(conn)
    conn.execute(
        f"""
        INSERT INTO work_claims
          (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
        VALUES
          ({p}, 'item', {p}, 'exclusive', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """,
        (session_id, str(item_id)),
    )
    conn.commit()
    conn.close()


def _session_attribution(path, session_id="sess-1"):
    """Return current/recent attribution columns for a session."""
    conn = _conn(path)
    p = _p(conn)
    row = conn.execute(
        f"""
        SELECT current_item_id, recent_item_id, recent_item_status
        FROM harness_sessions
        WHERE session_id={p}
        """,
        (session_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "current_item_id": row[0],
        "recent_item_id": row[1],
        "recent_item_status": row[2],
    }


def _item_field(path, item_id, field):
    """Read a single field from an item."""
    conn = _conn(path)
    p = _p(conn)
    if field == "project":
        row = conn.execute(
            "SELECT p.slug FROM items i JOIN projects p ON p.id = i.project_id "
            f"WHERE i.id={p}",
            (item_id,),
        ).fetchone()
    else:
        row = conn.execute(
            f"SELECT {field} FROM items WHERE id={p}", (item_id,)
        ).fetchone()
    conn.close()
    return row[0] if row else None


def _seed_qa_requirement(
    path,
    *,
    item_id,
    qa_kind="browser_smoke",
    qa_phase="verification",
    blocking_mode="blocking",
    success_policy="seeded-by-test",
):
    """Insert a QA requirement for backlog gate regression tests."""
    conn = _conn(path)
    p = _p(conn)
    cur = conn.execute(
        f"""
        INSERT INTO qa_requirements (
            item_id, qa_kind, qa_phase, blocking_mode, requirement_source, success_policy, created_at
        ) VALUES ({p}, {p}, {p}, {p}, 'seeded_default', {p}, {p}) RETURNING id
        """,
        (item_id, qa_kind, qa_phase, blocking_mode, success_policy, "2026-01-01T00:00:00Z"),
    )
    req_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return req_id


def _seed_qa_run(
    path,
    *,
    requirement_id,
    verdict="pass",
    executor_type="browser_substrate",
    raw_result=None,
    created_at=None,
):
    """Insert a QA run for backlog gate regression tests."""
    conn = _conn(path)
    ts = created_at or "2026-01-01T00:00:00Z"
    p = _p(conn)
    cur = conn.execute(
        f"""
        INSERT INTO qa_runs (qa_requirement_id, executor_type, qa_kind, verdict, raw_result, created_at)
        VALUES ({p}, {p}, 'browser_smoke', {p}, {p}, {p}) RETURNING id
        """,
        (requirement_id, executor_type, verdict, raw_result, ts),
    )
    run_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return run_id


def _seed_qa_artifact(path, *, run_id, artifact_path):
    """Insert a QA artifact row for authoritative browser evidence tests.

    ``artifact_path`` is recorded as an explicit local artifact handle.
    """
    from yoke_core.domain.qa_artifact_handle import (
        local_handle,
        serialize_handle,
    )

    conn = _conn(path)
    p = _p(conn)
    conn.execute(
        f"""
        INSERT INTO qa_artifacts (qa_run_id, artifact_type, content_type, artifact_handle, created_at)
        VALUES ({p}, 'screenshot', 'image/png', {p}, {p})
        """,
        (run_id, serialize_handle(local_handle(artifact_path)), "2026-01-01T00:00:00Z"),
    )
    conn.commit()
    conn.close()


class _PatchExternals:
    """Context manager that mocks all external side effects.

    Patches rendering functions on ``backlog_rendering`` (where
    ``backlog_updates`` looks them up via the ``_rendering`` alias) and
    mutation helpers on ``backlog_updates`` directly.
    """

    def __enter__(self):
        def create_config_value(key: str, default: str, **_kwargs: object) -> str:
            # Insulate tests from the developer's real machine config.
            return default

        self._create_config_patcher = mock.patch(
            "yoke_core.domain.runtime_settings.get_str",
            side_effect=create_config_value,
        )
        # Pin the session/auth source-actor ladder to the canonical fixture
        # actor; the real ladder is covered by
        # test_backlog_create_op_actor_resolution.py.
        self._source_actor_patcher = mock.patch(
            "yoke_core.domain.backlog_create_op._resolve_session_source_actor",
            return_value=int(DEFAULT_ITEM_ACTOR_ID),
        )
        self._rendering_patcher = mock.patch.multiple(
            backlog_rendering,
            _rebuild_board=mock.DEFAULT,
            _emit_event=mock.DEFAULT,
            _sync_item=mock.DEFAULT,
            _sync_labels=mock.MagicMock(return_value=True),
            _close_issue=mock.DEFAULT,
            _sync_title=mock.MagicMock(return_value=True),
            _sync_frozen_label=mock.MagicMock(return_value=True),
            _post_comment=mock.DEFAULT,
            _sync_body=mock.MagicMock(return_value=(True, "full")),
            _render_body=mock.MagicMock(return_value=True),
            _record_sync_failure=mock.DEFAULT,
        )
        self._updates_patcher = mock.patch.multiple(
            backlog_updates,
            _cascade_epic_tasks=mock.DEFAULT,
        )
        config_mock = self._create_config_patcher.__enter__()
        source_actor_mock = self._source_actor_patcher.__enter__()
        rendering_mocks = self._rendering_patcher.__enter__()
        updates_mocks = self._updates_patcher.__enter__()
        merged = dict(rendering_mocks)
        merged.update(updates_mocks)
        merged["create_config_value"] = config_mock
        merged["resolve_session_source_actor"] = source_actor_mock
        return merged

    def __exit__(self, *exc_info):
        self._updates_patcher.__exit__(*exc_info)
        self._rendering_patcher.__exit__(*exc_info)
        self._source_actor_patcher.__exit__(*exc_info)
        self._create_config_patcher.__exit__(*exc_info)


def _patch_externals():
    return _PatchExternals()
