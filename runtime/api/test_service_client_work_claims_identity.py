"""Self-only identity tests for ``claim-work`` / ``release-work-claim``.

Covers ACs 1-10 of the self-only identity contract: the explicit
``--session-id`` flag must equal the ambient session, an unprovable
explicit value is never authority, and ``--allow-non-terminal`` cannot
bypass the check.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone

from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.api.service_client_work_claims_identity import (
    ERROR_CODE_AMBIENT_MISSING,
    ERROR_CODE_MISMATCH,
    check_self_only_session_identity,
)
from runtime.api.test_service_client import (
    _REPO_ROOT,
    _service_client_cmd,
    _with_source_pythonpath,
)
from runtime.api.test_service_client_sessions_helpers import session_offer_db  # noqa: F401


_FRESH_TS = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
_SESSION_VAR_CHAIN = ("YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID")


def _run_with_ambient(
    args: list[str],
    *,
    db_path: str,
    ambient_session: str | None,
) -> subprocess.CompletedProcess:
    """Invoke the service client with a pinned ambient session id.

    Unlike ``test_service_client._run_client``, this helper does NOT
    auto-derive ambient from ``--session-id``. The whole point of the
    self-only check is that ambient and explicit can diverge; the
    tests need full control over both axes.
    """
    env = os.environ.copy()
    for var in _SESSION_VAR_CHAIN:
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
            "execution_lane, workspace, mode, offered_at, last_heartbeat) "
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
            "INSERT INTO work_claims (session_id, target_kind, item_id, claim_type, "
            "claimed_at, last_heartbeat) VALUES (%s, 'item', %s, 'exclusive', %s, %s)",
            (session_id, item_id, _FRESH_TS, _FRESH_TS),
        )
        conn.commit()
    finally:
        conn.close()


def _open_claim_row(db_path: str, item_id: int):
    conn = connect_test_db(db_path)
    try:
        return conn.execute(
            "SELECT session_id, released_at, release_reason FROM work_claims "
            "WHERE target_kind='item' AND item_id=%s AND released_at IS NULL",
            (item_id,),
        ).fetchone()
    finally:
        conn.close()


def _override_event_count(db_path: str, item_id: int) -> int:
    conn = connect_test_db(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_name='ItemClaimReleaseOverride' "
            "AND item_id=%s",
            (str(item_id),),
        ).fetchone()
    finally:
        conn.close()
    return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# Pure-Python contract — check_self_only_session_identity
# ---------------------------------------------------------------------------


class TestIdentityCheckPure:
    def test_ambient_missing_with_explicit_refuses(self) -> None:
        outcome = check_self_only_session_identity(
            "sid-other", ambient_resolver=lambda: None,
        )
        assert outcome.ok is False
        assert outcome.code == ERROR_CODE_AMBIENT_MISSING
        assert outcome.effective_session_id is None

    def test_ambient_missing_without_explicit_refuses(self) -> None:
        outcome = check_self_only_session_identity(
            None, ambient_resolver=lambda: None,
        )
        assert outcome.ok is False
        assert outcome.code == ERROR_CODE_AMBIENT_MISSING

    def test_explicit_matches_ambient_accepts(self) -> None:
        outcome = check_self_only_session_identity(
            "sid-self", ambient_resolver=lambda: "sid-self",
        )
        assert outcome.ok is True
        assert outcome.effective_session_id == "sid-self"
        assert outcome.code is None

    def test_explicit_omitted_falls_back_to_ambient(self) -> None:
        outcome = check_self_only_session_identity(
            None, ambient_resolver=lambda: "sid-self",
        )
        assert outcome.ok is True
        assert outcome.effective_session_id == "sid-self"

    def test_explicit_mismatch_refuses(self) -> None:
        outcome = check_self_only_session_identity(
            "sid-other", ambient_resolver=lambda: "sid-self",
        )
        assert outcome.ok is False
        assert outcome.code == ERROR_CODE_MISMATCH
        assert "sid-other" in (outcome.message or "")
        assert "sid-self" in (outcome.message or "")



# ---------------------------------------------------------------------------
# CLI contract — claim-work
# ---------------------------------------------------------------------------


class TestClaimWorkSelfOnly:
    def test_mismatched_session_id_refuses_before_mutation(
        self, session_offer_db,
    ) -> None:
        """AC-1, AC-2, AC-6: explicit OTHER with ambient SELF is rejected."""
        db_path = session_offer_db["db_path"]
        tmp_dir = session_offer_db["tmp_dir"]
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
                "SELECT COUNT(*) FROM work_claims WHERE target_kind='item' "
                "AND item_id=10",
            ).fetchone()
        finally:
            conn.close()
        assert rows[0] == 0

    def test_explicit_session_without_ambient_refuses(
        self, session_offer_db,
    ) -> None:
        """AC-7: an unprovable explicit value is never authority."""
        db_path = session_offer_db["db_path"]
        tmp_dir = session_offer_db["tmp_dir"]
        _seed_session(db_path, "sid-self", tmp_dir=tmp_dir)

        result = _run_with_ambient(
            ["claim-work", "--session-id", "sid-self", "--item", "YOK-10"],
            db_path=db_path,
            ambient_session=None,
        )
        assert result.returncode != 0
        err = json.loads(result.stderr)
        assert err["code"] == ERROR_CODE_AMBIENT_MISSING

    def test_explicit_matches_ambient_succeeds(self, session_offer_db) -> None:
        """AC-9 happy path: explicit SELF with ambient SELF claims the item."""
        db_path = session_offer_db["db_path"]
        tmp_dir = session_offer_db["tmp_dir"]
        _seed_session(db_path, "sid-self", tmp_dir=tmp_dir)

        result = _run_with_ambient(
            ["claim-work", "--session-id", "sid-self", "--item", "YOK-10"],
            db_path=db_path,
            ambient_session="sid-self",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        out = json.loads(result.stdout)
        assert out["success"] is True

        row = _open_claim_row(db_path, item_id=10)
        assert row is not None
        assert row[0] == "sid-self"

    def test_omitted_explicit_uses_ambient(self, session_offer_db) -> None:
        """AC-9: omitting --session-id falls back to the ambient session."""
        db_path = session_offer_db["db_path"]
        tmp_dir = session_offer_db["tmp_dir"]
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


# ---------------------------------------------------------------------------
# CLI contract — release-work-claim
# ---------------------------------------------------------------------------


class TestReleaseWorkClaimSelfOnly:
    def test_mismatched_release_leaves_holder_claim_intact(
        self, session_offer_db,
    ) -> None:
        """AC-3, AC-7: ordinary release cannot release another session's claim."""
        db_path = session_offer_db["db_path"]
        tmp_dir = session_offer_db["tmp_dir"]
        _seed_session(db_path, "sid-holder", tmp_dir=tmp_dir)
        _seed_session(db_path, "sid-self", tmp_dir=tmp_dir)
        _seed_active_claim(db_path, "sid-holder", item_id=10)

        result = _run_with_ambient(
            ["release-work-claim", "--session-id", "sid-holder",
             "--item", "YOK-10", "--reason", "completed"],
            db_path=db_path,
            ambient_session="sid-self",
        )
        assert result.returncode != 0
        err = json.loads(result.stderr)
        assert err["code"] == ERROR_CODE_MISMATCH

        # The holder claim is still open.
        row = _open_claim_row(db_path, item_id=10)
        assert row is not None
        assert row[0] == "sid-holder"
        assert row[1] is None

    def test_mismatched_release_with_override_flags_is_denied(
        self, session_offer_db,
    ) -> None:
        """AC-8: --allow-non-terminal --override-rationale does not bypass.

        The self-only check fires before ``emit_release_override`` can
        write an ``ItemClaimReleaseOverride`` audit event.
        """
        db_path = session_offer_db["db_path"]
        tmp_dir = session_offer_db["tmp_dir"]
        _seed_session(db_path, "sid-holder", tmp_dir=tmp_dir)
        _seed_session(db_path, "sid-self", tmp_dir=tmp_dir)
        _seed_active_claim(db_path, "sid-holder", item_id=10)

        result = _run_with_ambient(
            [
                "release-work-claim", "--session-id", "sid-holder",
                "--item", "YOK-10", "--reason", "handoff",
                "--allow-non-terminal",
                "--override-rationale", "operator wants override",
            ],
            db_path=db_path,
            ambient_session="sid-self",
        )
        assert result.returncode != 0
        err = json.loads(result.stderr)
        assert err["code"] == ERROR_CODE_MISMATCH

        row = _open_claim_row(db_path, item_id=10)
        assert row is not None
        assert row[0] == "sid-holder"
        assert row[1] is None
        assert _override_event_count(db_path, item_id=10) == 0

    def test_self_release_still_works(self, session_offer_db) -> None:
        """AC-4: holder's own release still succeeds when explicit matches ambient."""
        db_path = session_offer_db["db_path"]
        tmp_dir = session_offer_db["tmp_dir"]
        _seed_session(db_path, "sid-self", tmp_dir=tmp_dir)
        _seed_active_claim(db_path, "sid-self", item_id=10)

        result = _run_with_ambient(
            ["release-work-claim", "--session-id", "sid-self",
             "--item", "YOK-10", "--reason", "completed"],
            db_path=db_path,
            ambient_session="sid-self",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        out = json.loads(result.stdout)
        assert out["success"] is True

        conn = connect_test_db(db_path)
        try:
            row = conn.execute(
                "SELECT released_at, release_reason FROM work_claims "
                "WHERE target_kind='item' AND item_id=10",
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row[0] is not None
        assert row[1] == "completed"
