"""Domain-level coverage for the no-flags session-end auto-release helper.

Covers ``release_session_claims`` payload shape and edge cases that the
service-client layer does not exercise (no-claims fast path, multi-claim
ordering, target-kind discrimination on the response envelope). The
end-to-end CLI regression lives in
``runtime/api/test_service_client_sessions_end_claim_release.py``.
"""

from __future__ import annotations

import pytest


from runtime.api.test_sessions import _register, conn  # noqa: F401  (Postgres-backed pytest fixture)
from yoke_core.domain.sessions import (
    claim_work,
    end_session,
)
from yoke_core.domain.sessions_render_end_claim_release import (
    NO_FLAGS_RELEASE_VIA,
    SESSION_ENDED_RELEASE_REASON,
    release_session_claims,
)
from yoke_core.domain.work_claim_targets import (
    TARGET_KIND_EPIC_TASK,
    TARGET_KIND_ITEM,
)


def _claim_rows(conn, session_id: str):
    return conn.execute(
        """SELECT id, target_kind, item_id, epic_id, task_num,
                  process_key, conflict_group
           FROM work_claims
           WHERE session_id = %s AND released_at IS NULL
           ORDER BY claimed_at ASC, id ASC""",
        (session_id,),
    ).fetchall()


class TestReleaseSessionClaims:
    """release_session_claims payload + event shape."""

    def test_empty_active_claim_rows_returns_empty_and_emits_nothing(self, conn):
        _register(conn)
        result = release_session_claims(conn, "sess-1", active_claim_rows=[])
        assert result == []

    def test_item_claim_payload_carries_target_identifiers(self, conn):
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id="YOK-501")

        rows = _claim_rows(conn, "sess-1")
        released = release_session_claims(
            conn, "sess-1", active_claim_rows=rows,
        )

        assert len(released) == 1
        entry = released[0]
        assert entry["target_kind"] == TARGET_KIND_ITEM
        assert entry["item_id"] == 501
        assert "claim_id" in entry
        # No epic_task / process keys on item-target payload
        assert "epic_id" not in entry
        assert "process_key" not in entry

        # Claim is now released with the canonical reason
        stored = conn.execute(
            "SELECT release_reason FROM work_claims WHERE id = %s",
            (entry["claim_id"],),
        ).fetchone()
        assert stored["release_reason"] == SESSION_ENDED_RELEASE_REASON

    def test_epic_task_claim_payload_carries_epic_and_task_num(self, conn):
        _register(conn)
        # Insert an epic_task work-claim directly; claim_work() is item-only.
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, epic_id, task_num,
                claim_type, claimed_at, last_heartbeat)
               VALUES (%s, 'epic_task', 4242, 3, 'exclusive',
                       '2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z')""",
            ("sess-1",),
        )
        conn.commit()

        rows = _claim_rows(conn, "sess-1")
        released = release_session_claims(
            conn, "sess-1", active_claim_rows=rows,
        )

        assert len(released) == 1
        entry = released[0]
        assert entry["target_kind"] == TARGET_KIND_EPIC_TASK
        assert entry["epic_id"] == 4242
        assert entry["task_num"] == 3
        assert "item_id" not in entry

    def test_end_session_via_no_flags_constant(self):
        """The via marker is stable so audit callers can query for it."""
        assert NO_FLAGS_RELEASE_VIA == "no_flags"
        assert SESSION_ENDED_RELEASE_REASON == "session_ended"


class TestEndSessionResponseEnvelope:
    """The session row returned by end_session carries released_claims when populated."""

    def test_no_claims_no_released_claims_key(self, conn):
        """released_claims key is absent when nothing was released."""
        _register(conn)
        result = end_session(conn, "sess-1")
        assert "released_claims" not in result

    def test_with_claims_released_claims_in_response(self, conn):
        _register(conn)
        claim_work(conn, session_id="sess-1", item_id="YOK-777")
        result = end_session(conn, "sess-1")
        assert "released_claims" in result
        assert len(result["released_claims"]) == 1
        assert result["released_claims"][0]["item_id"] == 777
