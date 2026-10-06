"""A release caller must prove it is the session holding the claim."""

import json

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client_sessions_helpers import (
    session_test_db as session_test_db,
)
from runtime.api.test_service_client_work_claims_identity import (
    _open_claim_row,
    _override_event_count,
    _run_with_ambient,
    _seed_active_claim,
    _seed_session,
)
from yoke_core.api.service_client_work_claims_identity import ERROR_CODE_MISMATCH
from yoke_core.domain.work_claim_targets import make_item_target


class TestReleaseWorkClaimSelfOnly:
    def test_mismatched_release_leaves_holder_claim_intact(
        self, session_test_db
    ) -> None:
        """Ordinary release cannot release another session's claim."""
        db_path = session_test_db["db_path"]
        tmp_dir = session_test_db["tmp_dir"]
        _seed_session(db_path, "sid-holder", tmp_dir=tmp_dir)
        _seed_session(db_path, "sid-self", tmp_dir=tmp_dir)
        _seed_active_claim(db_path, "sid-holder", item_id=10)

        result = _run_with_ambient(
            [
                "release-work-claim",
                "--session-id",
                "sid-holder",
                "--item",
                "YOK-10",
                "--reason",
                "completed",
            ],
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
        self, session_test_db
    ) -> None:
        """--allow-non-terminal --override-rationale does not bypass.

        The self-only check fires before ``emit_release_override`` can
        write an ``ItemClaimReleaseOverride`` audit event.
        """
        db_path = session_test_db["db_path"]
        tmp_dir = session_test_db["tmp_dir"]
        _seed_session(db_path, "sid-holder", tmp_dir=tmp_dir)
        _seed_session(db_path, "sid-self", tmp_dir=tmp_dir)
        _seed_active_claim(db_path, "sid-holder", item_id=10)

        result = _run_with_ambient(
            [
                "release-work-claim",
                "--session-id",
                "sid-holder",
                "--item",
                "YOK-10",
                "--reason",
                "handoff",
                "--allow-non-terminal",
                "--override-rationale",
                "operator wants override",
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

    def test_self_release_still_works(self, session_test_db) -> None:
        """Holder's own release still succeeds when explicit matches ambient."""
        db_path = session_test_db["db_path"]
        tmp_dir = session_test_db["tmp_dir"]
        _seed_session(db_path, "sid-self", tmp_dir=tmp_dir)
        _seed_active_claim(db_path, "sid-self", item_id=10)

        result = _run_with_ambient(
            [
                "release-work-claim",
                "--session-id",
                "sid-self",
                "--item",
                "YOK-10",
                "--reason",
                "completed",
            ],
            db_path=db_path,
            ambient_session="sid-self",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        out = json.loads(result.stdout)
        assert out["success"] is True

        conn = connect_test_db(db_path)
        try:
            row = conn.execute(
                "SELECT released_at, release_reason FROM work_claims WHERE target_kind='item' AND scope=%s",
                (make_item_target(10).scope_json(),),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row[0] is not None
        assert row[1] == "completed"
