# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from yoke_contracts.timestamps import format_instant

from runtime.api.domain.merge_queue_observer_test_helpers import (
    INJECTED_AT,
    inject,
    message_body,
    message_count,
    message_id_for,
)

from runtime.api.domain.session_message_support_test_support import message_connection

from yoke_core.domain.session_ci_wait_observer import (
    apply_received_wait,
    observe_pending_ci_runs,
)

from yoke_core.domain.session_ci_wait_schema import ensure_session_ci_wait_schema

NOW = datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc)

SESSION = "s1"

RUN_ID = "33903192687"

HEAD_SHA = "ab" * 20


@pytest.fixture()
def waiting_connection():
    """One session owed one pending CI verdict."""
    conn = message_connection()
    ensure_session_ci_wait_schema(conn)
    conn.executescript(
        "CREATE TABLE project_github_repo_bindings "
        "(project_id INTEGER, github_repo TEXT, status TEXT);"
        "INSERT INTO project_github_repo_bindings VALUES (1,'acme/widgets','active');"
    )
    conn.execute(
        "INSERT INTO session_ci_run_waits "
        "(session_id,project_id,repo,run_id,head_sha,kind,continue_command,"
        "created_at) VALUES (?,1,'acme/widgets',?,?,'selection',?,?)",
        (
            SESSION,
            RUN_ID,
            HEAD_SHA,
            "yoke watch pytest --impacted main --bounded",
            "2026-09-04T17:40:00Z",
        ),
    )
    conn.commit()
    return conn


def _wait_row(conn):
    return conn.execute(
        "SELECT conclusion, notified_at, read_at FROM session_ci_run_waits"
    ).fetchone()
