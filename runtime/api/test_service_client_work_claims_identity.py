"""Work claims require the ambient session, even with a release override."""

# ruff: noqa: F811 -- imported pytest fixtures are intentionally re-exported.

from __future__ import annotations

from runtime.api.service_client_work_claims_identity_test_support import (
    _FRESH_TS as _FRESH_TS,
    _open_claim_row as _open_claim_row,
    _override_event_count as _override_event_count,
    _run_with_ambient as _run_with_ambient,
    _seed_active_claim as _seed_active_claim,
    _seed_session as _seed_session,
)


import json

from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.api.service_client_work_claims_identity import (
    ERROR_CODE_AMBIENT_MISSING,
    ERROR_CODE_MISMATCH,
    check_self_only_session_identity,
)
from yoke_core.domain.work_claim_targets import make_item_target
from runtime.api.service_client_sessions_helpers_test_support import session_test_db  # noqa: F401


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
