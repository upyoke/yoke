# ruff: noqa: E402, F401, F811 -- imported pytest fixtures are intentionally re-exported.
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import os

import subprocess

from datetime import datetime, timezone

from yoke_contracts.session_identity import AMBIENT_ENV_VARS

from runtime.api.fixtures.file_test_db import connect_test_db

from yoke_core.api.service_client_work_claims_identity import (
    ERROR_CODE_AMBIENT_MISSING,
    ERROR_CODE_MISMATCH,
    check_self_only_session_identity,
)

from yoke_core.domain.work_claim_targets import make_item_target

from runtime.api.service_client_test_support import (
    _REPO_ROOT,
    _service_client_cmd,
    _with_source_pythonpath,
)

from runtime.api.service_client_sessions_helpers_test_support import session_test_db  # noqa: F401

_FRESH_TS = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_with_ambient(
    args: list[str], *, db_path: str, ambient_session: str | None
) -> subprocess.CompletedProcess:
    """Invoke the service client with a pinned ambient session id.

    Unlike ``test_service_client._run_client``, this helper does NOT
    auto-derive ambient from ``--session-id``. The whole point of the
    self-only check is that ambient and explicit can diverge; the
    tests need full control over both axes.
    """
    env = os.environ.copy()
    for var in AMBIENT_ENV_VARS:
        env.pop(var, None)
    if ambient_session is not None:
        env["YOKE_SESSION_ID"] = ambient_session
    env["YOKE_DB"] = db_path
    return subprocess.run(
        _service_client_cmd(args),
        capture_output=True,
        text=True,
        env=_with_source_pythonpath(env),
        cwd=_REPO_ROOT,
        timeout=30,
    )


def _seed_session(db_path: str, session_id: str, *, tmp_dir: str) -> None:
    conn = connect_test_db(db_path)
    try:
        conn.execute(
            "INSERT INTO harness_sessions (session_id, executor, provider, model, reasoning_effort, "
            "execution_level, workspace, mode, offered_at, last_heartbeat) "
            "VALUES (%s, 'claude-code', 'anthropic', 'claude-opus-5-5', 'medium', 'SENIOR', %s, 'hook', "
            "%s, %s)",
            (session_id, tmp_dir, _FRESH_TS, _FRESH_TS),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_active_claim(db_path: str, session_id: str, item_id: int) -> None:
    conn = connect_test_db(db_path)
    try:
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, scope, claim_type, claimed_at, last_heartbeat) VALUES (%s, 'item', %s, 'exclusive', %s, %s)",
            (session_id, make_item_target(item_id).scope_json(), _FRESH_TS, _FRESH_TS),
        )
        conn.commit()
    finally:
        conn.close()


def _open_claim_row(db_path: str, item_id: int):
    conn = connect_test_db(db_path)
    try:
        return conn.execute(
            "SELECT session_id, released_at, release_reason FROM work_claims WHERE target_kind='item' AND scope=%s AND released_at IS NULL",
            (make_item_target(item_id).scope_json(),),
        ).fetchone()
    finally:
        conn.close()


def _override_event_count(db_path: str, item_id: int) -> int:
    conn = connect_test_db(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_name='ItemClaimReleaseOverride' AND item_id=%s",
            (str(item_id),),
        ).fetchone()
    finally:
        conn.close()
    return int(row[0]) if row else 0
