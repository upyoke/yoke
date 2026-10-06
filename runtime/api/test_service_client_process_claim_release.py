"""Process claims release through their typed scope."""

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import (
    session_test_db as session_test_db,
)
from yoke_core.domain.work_claim_targets import make_process_target


class TestReleaseProcessClaim:
    def test_release_process_claim_by_key(self, session_test_db):
        """Process targets release through --process KEY rather than --item.

        Replaces the legacy "sentinel claim" test: STRATEGIZE/FEED are now
        first-class process targets in the typed-target world, not pseudo-items.
        """
        db_path = session_test_db["db_path"]
        sid = "release-process-test"

        conn = connect_test_db(db_path)
        conn.execute(
            "INSERT INTO harness_sessions (session_id, executor, provider, model, "
            "execution_lane, workspace, mode, offered_at, last_heartbeat) "
            "VALUES (%s, 'claude-code', 'anthropic', 'opus', 'primary', %s, 'hook', "
            "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
            (sid, session_test_db["tmp_dir"]),
        )
        conn.execute(
            "INSERT INTO work_claims (session_id, target_kind, scope, "
            "claim_type, claimed_at, last_heartbeat) "
            "VALUES (%s, 'process', %s, "
            "'exclusive', '2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
            (sid, make_process_target("STRATEGIZE", "yoke").scope_json()),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            [
                "release-work-claim",
                "--session-id",
                sid,
                "--process",
                "STRATEGIZE",
                "--project",
                "yoke",
                "--reason",
                "completed",
            ],
            db_path=db_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT released_at, release_reason FROM work_claims WHERE session_id = %s AND target_kind='process' AND scope = %s",
            (sid, make_process_target("STRATEGIZE", "yoke").scope_json()),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] is not None
        assert row[1] == "completed"
