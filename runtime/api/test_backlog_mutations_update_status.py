"""ExecuteUpdate sub-scenarios: status transitions, claim guards, handoff release.

Covers basic status updates, session-attribution side effects, claim-denied
errors (including remediation hints), the YOKE_CLAIM_BYPASS escape hatch,
and the post-handoff-release denial paths for both same-session and other-
session callers.
"""

from __future__ import annotations

import io
import os
from unittest import mock

from runtime.api.backlog_mutations_test_helpers import (
    _conn,
    _item_field,
    _patch_externals,
    _seed_claim,
    _seed_item,
    _seed_session,
    _session_attribution,
    tmp_db,  # noqa: F401 — re-exported fixture
)
from yoke_core.domain import backlog


class TestExecuteUpdate:
    """ExecuteUpdate sub-scenarios: status, claims, handoff release."""

    def test_basic_status_update(self, tmp_db):
        _seed_item(tmp_db, id=10, status="idea")
        _seed_session(tmp_db)
        _seed_claim(tmp_db, item_id="10")
        out = io.StringIO()
        with _patch_externals() as patched, \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_update(
                item_id=10,
                field="status",
                value="refining-idea",
                session_id="sess-1",
                out=out,
            )
        assert result["success"] is True
        assert _item_field(tmp_db, 10, "status") == "refining-idea"
        patched["_rebuild_board"].assert_called_once_with(out)

    def test_status_update_sets_session_current_item(self, tmp_db):
        _seed_item(tmp_db, id=10, status="idea")
        _seed_item(tmp_db, id=8, status="planned")
        _seed_session(tmp_db)
        _seed_claim(tmp_db, item_id="10")
        conn = _conn(tmp_db)
        conn.execute(
            """
            UPDATE harness_sessions
            SET current_item_id='8', current_item_set_at='2026-01-01T00:00:00Z'
            WHERE session_id='sess-1'
            """
        )
        conn.commit()
        conn.close()
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_update(
                item_id=10,
                field="status",
                value="refining-idea",
                session_id="sess-1",
                out=out,
            )
        assert result["success"] is True
        attribution = _session_attribution(tmp_db)
        assert attribution["current_item_id"] == "10"
        assert attribution["recent_item_id"] == "8"

    def test_status_update_denied_without_session_id(self, tmp_db):
        _seed_item(tmp_db, id=10, status="idea")
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}, clear=False):
            os.environ.pop("YOKE_SESSION_ID", None)
            os.environ.pop("CLAUDE_SESSION_ID", None)
            os.environ.pop("CODEX_THREAD_ID", None)
            result = backlog.execute_update(
                item_id=10,
                field="status",
                value="refining-idea",
                out=out,
            )
        assert result["success"] is False
        assert "request session_id is required" in result["error"]
        assert _item_field(tmp_db, 10, "status") == "idea"

    def test_status_update_denied_when_claim_held_by_other_session(self, tmp_db):
        _seed_item(tmp_db, id=10, status="idea")
        _seed_session(tmp_db, session_id="sess-1")
        _seed_session(tmp_db, session_id="sess-2")
        _seed_claim(tmp_db, session_id="sess-2", item_id="10")
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_update(
                item_id=10,
                field="status",
                value="refining-idea",
                session_id="sess-1",
                out=out,
            )
        assert result["success"] is False
        assert "claim held by different session sess-2" in result["error"]
        assert _item_field(tmp_db, 10, "status") == "idea"

    def test_claim_denied_error_includes_remediation_hints(self, tmp_db):
        """Error body must point at claim-work, repair_status, and the bypass env var.

        Covers three branches: no session id, no active claim, wrong session.
        """
        _seed_item(tmp_db, id=10, status="idea")
        _seed_session(tmp_db, session_id="sess-1")
        _seed_session(tmp_db, session_id="sess-2")

        required_hints = (
            "python3 -m yoke_core.api.service_client claim-work",
            "--item YOK-10",
            "python3 -m yoke_core.engines.repair_status",
            "YOKE_CLAIM_BYPASS",
        )

        def _assert_hints(error: str) -> None:
            for snippet in required_hints:
                assert snippet in error, f"missing {snippet!r} in {error!r}"

        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}, clear=False):
            os.environ.pop("YOKE_SESSION_ID", None)
            os.environ.pop("CLAUDE_SESSION_ID", None)
            os.environ.pop("CODEX_THREAD_ID", None)
            os.environ.pop("YOKE_CLAIM_BYPASS", None)
            no_session = backlog.execute_update(
                item_id=10, field="status", value="refining-idea", out=io.StringIO(),
            )
        assert no_session["success"] is False
        _assert_hints(no_session["error"])

        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            no_claim = backlog.execute_update(
                item_id=10,
                field="status",
                value="refining-idea",
                session_id="sess-1",
                out=io.StringIO(),
            )
        assert no_claim["success"] is False
        _assert_hints(no_claim["error"])

        _seed_claim(tmp_db, session_id="sess-2", item_id="10")
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            wrong_session = backlog.execute_update(
                item_id=10,
                field="status",
                value="refining-idea",
                session_id="sess-1",
                out=io.StringIO(),
            )
        assert wrong_session["success"] is False
        _assert_hints(wrong_session["error"])

    def test_status_update_bypass_allows_claimless_transition(self, tmp_db):
        _seed_item(tmp_db, id=10, status="idea")
        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(
                 os.environ,
                 {"YOKE_DB": tmp_db, "YOKE_CLAIM_BYPASS": "test-bypass"},
             ):
            result = backlog.execute_update(
                item_id=10,
                field="status",
                value="refining-idea",
                out=out,
            )
        assert result["success"] is True
        assert _item_field(tmp_db, 10, "status") == "refining-idea"

    def test_status_update_denied_after_handoff_release_for_same_session(self, tmp_db):
        _seed_item(tmp_db, id=10, status="reviewed-implementation")
        _seed_session(tmp_db)
        _seed_claim(tmp_db, item_id="10")
        conn = _conn(tmp_db)
        conn.execute(
            """
            UPDATE work_claims
            SET released_at='2026-01-01T00:05:00Z', release_reason='handed_off'
            WHERE item_id='10' AND released_at IS NULL
            """
        )
        conn.commit()
        conn.close()

        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_update(
                item_id=10,
                field="status",
                value="implemented",
                session_id="sess-1",
                out=out,
            )

        assert result["success"] is False
        assert "no active claim on YOK-10" in result["error"]
        assert _item_field(tmp_db, 10, "status") == "reviewed-implementation"

    def test_status_update_denied_for_other_session_after_handoff_release(self, tmp_db):
        _seed_item(tmp_db, id=10, status="reviewed-implementation")
        _seed_session(tmp_db, session_id="sess-1")
        _seed_session(tmp_db, session_id="sess-2")
        _seed_claim(tmp_db, session_id="sess-2", item_id="10")
        conn = _conn(tmp_db)
        conn.execute(
            """
            UPDATE work_claims
            SET released_at='2026-01-01T00:05:00Z', release_reason='handed_off'
            WHERE item_id='10' AND released_at IS NULL
            """
        )
        conn.commit()
        conn.close()

        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_update(
                item_id=10,
                field="status",
                value="implemented",
                session_id="sess-1",
                out=out,
            )

        assert result["success"] is False
        assert "no active claim on YOK-10" in result["error"]
        assert _item_field(tmp_db, 10, "status") == "reviewed-implementation"

    def test_release_transition_denied_after_handoff_release_for_same_session(self, tmp_db):
        _seed_item(tmp_db, id=10, status="implemented")
        _seed_session(tmp_db)
        _seed_claim(tmp_db, item_id="10")
        conn = _conn(tmp_db)
        conn.execute(
            """
            UPDATE work_claims
            SET released_at='2026-01-01T00:05:00Z', release_reason='handed_off'
            WHERE item_id='10' AND released_at IS NULL
            """
        )
        conn.commit()
        conn.close()

        out = io.StringIO()
        with _patch_externals(), \
             mock.patch.dict(os.environ, {"YOKE_DB": tmp_db}):
            result = backlog.execute_update(
                item_id=10,
                field="status",
                value="release",
                session_id="sess-1",
                out=out,
            )

        assert result["success"] is False
        assert "no active claim on YOK-10" in result["error"]
        assert _item_field(tmp_db, 10, "status") == "implemented"
