"""Work claims require the ambient session, even with a release override."""

# ruff: noqa: F811 -- imported pytest fixtures are intentionally re-exported.

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
from runtime.api.test_service_client import (
    _REPO_ROOT,
    _service_client_cmd,
    _with_source_pythonpath,
)
from runtime.api.test_service_client_sessions_helpers import session_test_db  # noqa: F401


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
            "INSERT INTO harness_sessions (session_id, executor, provider, model, "
            "execution_level, workspace, mode, offered_at, last_heartbeat) "
            "VALUES (%s, 'claude-code', 'anthropic', 'opus', 'primary', %s, 'hook', "
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


# Pure-Python contract — check_self_only_session_identity


class TestIdentityCheckPure:
    def test_ambient_missing_with_explicit_refuses(self) -> None:
        outcome = check_self_only_session_identity(
            "sid-other", ambient_resolver=lambda: None
        )
        assert outcome.ok is False
        assert outcome.code == ERROR_CODE_AMBIENT_MISSING
        assert outcome.effective_session_id is None

    def test_ambient_missing_without_explicit_refuses(self) -> None:
        outcome = check_self_only_session_identity(None, ambient_resolver=lambda: None)
        assert outcome.ok is False
        assert outcome.code == ERROR_CODE_AMBIENT_MISSING

    def test_explicit_matches_ambient_accepts(self) -> None:
        outcome = check_self_only_session_identity(
            "sid-self", ambient_resolver=lambda: "sid-self"
        )
        assert outcome.ok is True
        assert outcome.effective_session_id == "sid-self"
        assert outcome.code is None

    def test_explicit_omitted_falls_back_to_ambient(self) -> None:
        outcome = check_self_only_session_identity(
            None, ambient_resolver=lambda: "sid-self"
        )
        assert outcome.ok is True
        assert outcome.effective_session_id == "sid-self"

    def test_explicit_mismatch_refuses(self) -> None:
        outcome = check_self_only_session_identity(
            "sid-other", ambient_resolver=lambda: "sid-self"
        )
        assert outcome.ok is False
        assert outcome.code == ERROR_CODE_MISMATCH
        assert "sid-other" in (outcome.message or "")
        assert "sid-self" in (outcome.message or "")


# CLI contract — claim-work


class TestClaimWorkSelfOnly:
    def test_mismatched_session_id_refuses_before_mutation(
        self, session_test_db
    ) -> None:
        """Explicit OTHER with ambient SELF is rejected."""
        db_path = session_test_db["db_path"]
        tmp_dir = session_test_db["tmp_dir"]
        _seed_session(db_path, "sid-self", tmp_dir=tmp_dir)
        _seed_session(db_path, "sid-other", tmp_dir=tmp_dir)

        result = _run_with_ambient(
            ["claim-work", "--session-id", "sid-other", "--item", "YOK-10"],
            db_path=db_path,
            ambient_session="sid-self",
        )
        assert result.returncode != 0
        err = json.loads(result.stderr)
        assert err["success"] is False
        assert err["code"] == ERROR_CODE_MISMATCH

        # No work_claims row landed for either session.
        conn = connect_test_db(db_path)
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM work_claims WHERE target_kind='item' AND scope=%s",
                (make_item_target(10).scope_json(),),
            ).fetchone()
        finally:
            conn.close()
        assert rows[0] == 0

    def test_explicit_session_without_ambient_refuses(self, session_test_db) -> None:
        """An unprovable explicit value is never authority."""
        db_path = session_test_db["db_path"]
        tmp_dir = session_test_db["tmp_dir"]
        _seed_session(db_path, "sid-self", tmp_dir=tmp_dir)

        result = _run_with_ambient(
            ["claim-work", "--session-id", "sid-self", "--item", "YOK-10"],
            db_path=db_path,
            ambient_session=None,
        )
        assert result.returncode != 0
        err = json.loads(result.stderr)
        assert err["code"] == ERROR_CODE_AMBIENT_MISSING

    def test_explicit_matches_ambient_succeeds(self, session_test_db) -> None:
        """Happy path: explicit SELF with ambient SELF claims the item."""
        db_path = session_test_db["db_path"]
        tmp_dir = session_test_db["tmp_dir"]
        _seed_session(db_path, "sid-self", tmp_dir=tmp_dir)

        result = _run_with_ambient(
            ["claim-work", "--session-id", "sid-self", "--item", "YOK-10"],
            db_path=db_path,
            ambient_session="sid-self",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        out = json.loads(result.stdout)
        assert out["success"] is True
        assert out["claim"]["scope"] == {"public_ref": "YOK-10"}

        row = _open_claim_row(db_path, item_id=10)
        assert row is not None
        assert row[0] == "sid-self"

    def test_omitted_explicit_uses_ambient(self, session_test_db) -> None:
        """Omitting --session-id falls back to the ambient session."""
        db_path = session_test_db["db_path"]
        tmp_dir = session_test_db["tmp_dir"]
        _seed_session(db_path, "sid-self", tmp_dir=tmp_dir)

        result = _run_with_ambient(
            ["claim-work", "--item", "YOK-10"],
            db_path=db_path,
            ambient_session="sid-self",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        out = json.loads(result.stdout)
        assert out["success"] is True

        row = _open_claim_row(db_path, item_id=10)
        assert row is not None
        assert row[0] == "sid-self"


# CLI contract — release-work-claim
# ---------------------------------------------------------------------------
