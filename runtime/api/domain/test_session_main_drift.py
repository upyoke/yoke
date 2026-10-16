"""Tests for session-visible local main drift advisories."""

from __future__ import annotations

import pytest
from yoke_contracts.hook_runner.client_facts import MAIN_HEAD_KEY, client_fact

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import (
    apply_test_schema,
    connect_test_db,
    init_test_db,
)
from yoke_core.domain.session_main_drift import check_drift


@pytest.fixture()
def drift_db(tmp_path):
    # Per-test DB on both engines: a SQLite file under tmp_path, or a
    # disposable per-test Postgres DB with YOKE_PG_DSN repointed for the
    # context's lifetime. The yield keeps the context (and the repointed
    # DSN) open across the whole test so ``check_drift`` and ``_session_row``
    # — both backend-routed through ``connect`` — share this DB.
    with init_test_db(tmp_path, apply_schema=apply_test_schema) as db_path:
        conn = connect_test_db(db_path)
        try:
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            conn.execute(
                f"INSERT INTO harness_sessions\n                   (project_id, session_id, executor, provider, model, execution_level,\n                    executor_version, machine_id, workspace, mode, offered_at, last_heartbeat)\n                   VALUES\n                   (1, 'sess-drift', 'codex', 'openai', 'test', 'primary', NULL, NULL,\n                    {p}, 'test', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
                (str(tmp_path),),
            )
            conn.commit()
        finally:
            conn.close()
        yield db_path


SHA_FIRST = "1" * 40
SHA_SECOND = "2" * 40
SHA_THIRD = "3" * 40


def _head(*commits: tuple[str, str]) -> dict:
    """The client's main-head fact: newest commit first."""
    return client_fact(MAIN_HEAD_KEY, {"commits": [list(c) for c in commits]})


def _session_row(db_path: str):
    conn = connect_test_db(db_path)
    try:
        return conn.execute(
            "SELECT last_seen_main_sha, last_drift_check_at "
            "FROM harness_sessions WHERE session_id='sess-drift'"
        ).fetchone()
    finally:
        conn.close()


def test_first_observation_records_main_without_advisory(drift_db) -> None:
    advisory = check_drift(
        "sess-drift",
        _head((SHA_FIRST, "first")),
        now="2026-01-01T00:00:00Z",
    )

    assert advisory is None
    assert _session_row(drift_db)["last_seen_main_sha"] == SHA_FIRST


def test_changed_main_returns_advisory_and_updates_seen_sha(drift_db) -> None:
    check_drift("sess-drift", _head((SHA_FIRST, "first")), now="2026-01-01T00:00:00Z")

    advisory = check_drift(
        "sess-drift",
        _head((SHA_SECOND, "second"), (SHA_FIRST, "first")),
        now="2026-01-01T00:02:00Z",
    )

    assert advisory is not None
    assert advisory.commits_ahead == 1
    assert advisory.oneline_summary == f"{SHA_SECOND[:10]} second"
    assert _session_row(drift_db)["last_seen_main_sha"] == SHA_SECOND


def test_previous_head_outside_window_counts_whole_window(drift_db) -> None:
    check_drift("sess-drift", _head((SHA_FIRST, "first")), now="2026-01-01T00:00:00Z")

    advisory = check_drift(
        "sess-drift",
        _head((SHA_THIRD, "third"), (SHA_SECOND, "second")),
        now="2026-01-01T00:02:00Z",
    )

    assert advisory is not None
    assert advisory.commits_ahead == 2
    assert advisory.oneline_summary == (
        f"{SHA_THIRD[:10]} third; {SHA_SECOND[:10]} second"
    )


def test_same_sha_and_throttle_return_no_advisory(drift_db) -> None:
    check_drift("sess-drift", _head((SHA_FIRST, "first")), now="2026-01-01T00:00:00Z")
    moved = _head((SHA_SECOND, "second"), (SHA_FIRST, "first"))

    throttled = check_drift("sess-drift", moved, now="2026-01-01T00:00:30Z")
    assert throttled is None

    same = check_drift(
        "sess-drift", _head((SHA_FIRST, "first")), now="2026-01-01T00:05:00Z"
    )
    assert same is None


def test_missing_main_head_fact_is_no_advisory(drift_db) -> None:
    assert check_drift("sess-drift", {}, now="2026-01-01T00:00:00Z") is None
    assert _session_row(drift_db)["last_seen_main_sha"] is None


def test_observe_pre_returns_drift_advisory_as_context(monkeypatch) -> None:
    from yoke_core.domain import observe_pre
    from yoke_core.domain.session_main_drift import DriftAdvisory
    from yoke_core.hooks.types import HookContext, Outcome

    monkeypatch.setattr(
        "yoke_core.domain.session_main_drift.check_drift",
        lambda *_, **__: DriftAdvisory("sess-drift", 2, "abc123 one; def456 two"),
    )
    monkeypatch.setattr(observe_pre, "_process_payload", lambda *_, **__: True)
    expected = "# advisory: another session committed 2 new commits to main:"

    advisory = observe_pre._session_main_drift_advisory(
        {"session_id": "sess-drift", "cwd": "/tmp/repo"},
    )
    assert advisory.startswith(expected)

    decision = observe_pre.evaluate(
        HookContext(
            event_name="PreToolUse",
            executor_family="claude",
            executor_surface="claude",
            payload={"session_id": "sess-drift", "cwd": "/tmp/repo"},
        )
    )
    assert decision.outcome is Outcome.NOOP
    assert decision.audit_fields["additionalContext"].startswith(expected)
