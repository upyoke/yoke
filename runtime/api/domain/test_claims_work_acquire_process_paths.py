"""Process work-claim acquisition is a pure process lock — no path claims.

The strategy authority is the ``strategy_docs`` DB table; the rendered
``.yoke/strategy/`` views are gitignored local caches that are never
committed, so acquiring a STRATEGIZE/FEED process claim registers no
linked path claims. Release still cascades *legacy* linked rows (claims
acquired before the retirement) through ``_release_linked_path_claims``.
"""

from __future__ import annotations

from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    conn,
    local_human,
    seed_test_holder_session,
)
from yoke_core.domain.sessions_lifecycle_claim import claim_work, release_claim
from yoke_core.domain.work_claim_targets import make_process_target
from yoke_core.domain.work_processes import PROCESS_DOCTOR, PROCESS_STRATEGIZE


def _claim_rows(conn, work_claim_id: int):
    return conn.execute(
        "SELECT id, state, released_at FROM path_claims "
        "WHERE work_claim_id = %s ORDER BY id",
        (work_claim_id,),
    ).fetchall()


class TestProcessAcquireIsPureLock:
    def test_strategize_acquire_registers_no_path_claims(self, conn):
        seed_test_holder_session(conn, session_id="sess-strategize")

        claim = claim_work(
            conn,
            session_id="sess-strategize",
            target=make_process_target(PROCESS_STRATEGIZE, "yoke"),
        )

        assert claim["linked_path_claim_ids"] == []
        assert _claim_rows(conn, int(claim["id"])) == []

    def test_strategize_reacquire_still_registers_none(self, conn):
        seed_test_holder_session(conn, session_id="sess-strategize")
        target = make_process_target(PROCESS_STRATEGIZE, "yoke")

        first = claim_work(conn, session_id="sess-strategize", target=target)
        second = claim_work(conn, session_id="sess-strategize", target=target)

        assert second["id"] == first["id"]
        assert second["linked_path_claim_ids"] == []
        assert _claim_rows(conn, int(first["id"])) == []

    def test_doctor_acquire_registers_no_path_claims(self, conn):
        seed_test_holder_session(conn, session_id="sess-doctor")

        claim = claim_work(
            conn,
            session_id="sess-doctor",
            target=make_process_target(PROCESS_DOCTOR, "yoke"),
        )

        assert claim["linked_path_claim_ids"] == []
        assert _claim_rows(conn, int(claim["id"])) == []


class TestLegacyLinkageRelease:
    def test_release_still_cascades_legacy_linked_path_claims(self, conn):
        """Pre-retirement claims carry linked rows; release reaps them."""
        session_id = "sess-strategize"
        seed_test_holder_session(conn, session_id=session_id)
        target = make_process_target(PROCESS_STRATEGIZE, "yoke")
        claim = claim_work(conn, session_id=session_id, target=target)
        work_claim_id = int(claim["id"])

        cur = conn.execute(
            "INSERT INTO path_claims (state, mode, actor_id, session_id, "
            "work_claim_id, owner_kind, owner_work_claim_id, "
            "integration_target, registered_at) "
            "VALUES ('planned', 'exclusive', %s, %s, %s, 'process', %s, "
            "'main', '2026-05-01T00:00:00Z') RETURNING id",
            (local_human(conn), session_id, work_claim_id, work_claim_id),
        )
        legacy_path_claim_id = int(cur.fetchone()[0])
        conn.commit()

        result = release_claim(conn, work_claim_id, reason="released")

        assert result["linked_path_claim_ids"] == [legacy_path_claim_id]
        rows = _claim_rows(conn, work_claim_id)
        assert len(rows) == 1
        assert rows[0]["released_at"] is not None
