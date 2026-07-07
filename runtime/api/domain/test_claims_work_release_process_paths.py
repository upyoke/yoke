"""Cascade release of process-linked path claims via the by-claim-id path.

The session-scoped release path already cascades linked process path
claims when a process work-claim releases. The function-call surface
(``claims.work.release``) and the HTTP route both call into
``sessions_lifecycle_claim.release_claim`` (which now delegates to
``sessions_lifecycle_claim_release.release_claim_by_id``). Coverage
here asserts:

* Process work-claim release by claim id moves its linked non-terminal
  path claims to ``released`` in the same transaction.
* The release path preserves audit evidence on the returned row -- the
  released work-claim row carries ``linked_path_claim_ids``.
* Item work-claim release does NOT touch path claims (item path
  lifecycle is owned elsewhere).
"""

from __future__ import annotations

from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    conn,
    seed_test_holder_session,
)
from yoke_core.domain.sessions_lifecycle_claim import release_claim


SESS = "sess-process-release"


def _seed_process_work_claim(conn, *, session_id: str, process_key: str) -> int:
    seed_test_holder_session(conn, session_id=session_id)
    cur = conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, process_key, "
        "conflict_group, claimed_at, last_heartbeat) "
        "VALUES (%s, 'process', %s, %s, '2026-05-01T00:00:00Z', "
        "'2026-05-01T00:00:00Z') RETURNING id",
        (session_id, process_key, f"strategy-control-plane:yoke"),
    )
    return int(cur.fetchone()[0])


def _seed_linked_path_claim(conn, *, work_claim_id: int, state: str = "active") -> int:
    cur = conn.execute(
        "INSERT INTO path_claims "
        "(state, mode, actor_id, integration_target, registered_at, "
        "work_claim_id, owner_kind, owner_work_claim_id) "
        "VALUES (%s, 'exclusive', 1, 'main', '2026-05-01T00:00:00Z', "
        "%s, 'process', %s) RETURNING id",
        (state, work_claim_id, work_claim_id),
    )
    return int(cur.fetchone()[0])


def _seed_item_work_claim(conn, *, session_id: str, item_id: int) -> int:
    seed_test_holder_session(conn, session_id=session_id)
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 't', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (item_id, item_id),
    )
    cur = conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, item_id, "
        "claimed_at, last_heartbeat) "
        "VALUES (%s, 'item', %s, '2026-05-01T00:00:00Z', "
        "'2026-05-01T00:00:00Z') RETURNING id",
        (session_id, item_id),
    )
    return int(cur.fetchone()[0])


class TestReleaseCascade:
    def test_process_release_cascades_linked_path_claims(self, conn):
        work_claim_id = _seed_process_work_claim(
            conn, session_id=SESS, process_key="STRATEGIZE",
        )
        pc_a = _seed_linked_path_claim(conn, work_claim_id=work_claim_id)
        pc_b = _seed_linked_path_claim(conn, work_claim_id=work_claim_id)
        conn.commit()

        result = release_claim(conn, work_claim_id, reason="released")

        # Both linked path claims now terminal.
        terminal = conn.execute(
            "SELECT id, state, released_at, release_reason "
            "FROM path_claims WHERE id IN (%s, %s)",
            (pc_a, pc_b),
        ).fetchall()
        assert len(terminal) == 2
        for row in terminal:
            assert row["state"] == "released"
            assert row["released_at"] is not None
            assert row["release_reason"] == "work-claim-released:released"

        # Audit evidence: the returned row exposes the cascaded ids.
        assert sorted(result.get("linked_path_claim_ids", [])) == sorted(
            [pc_a, pc_b]
        )

    def test_process_release_ignores_already_terminal_path_claims(self, conn):
        work_claim_id = _seed_process_work_claim(
            conn, session_id=SESS, process_key="STRATEGIZE",
        )
        live_pc = _seed_linked_path_claim(conn, work_claim_id=work_claim_id)
        stale_pc = _seed_linked_path_claim(
            conn, work_claim_id=work_claim_id, state="released",
        )
        # Mark stale_pc as already released so the cascade leaves it alone.
        conn.execute(
            "UPDATE path_claims SET released_at = '2026-04-30T00:00:00Z', "
            "release_reason = 'manual' WHERE id = %s",
            (stale_pc,),
        )
        conn.commit()

        result = release_claim(conn, work_claim_id, reason="released")

        assert result.get("linked_path_claim_ids") == [live_pc]
        stale_row = conn.execute(
            "SELECT released_at, release_reason FROM path_claims WHERE id = %s",
            (stale_pc,),
        ).fetchone()
        # Stale row's release timestamp + reason are NOT overwritten.
        assert stale_row["released_at"] == "2026-04-30T00:00:00Z"
        assert stale_row["release_reason"] == "manual"

    def test_item_release_does_not_touch_path_claims(self, conn):
        item_claim_id = _seed_item_work_claim(
            conn, session_id=SESS, item_id=50001,
        )
        unrelated_process_claim = _seed_process_work_claim(
            conn, session_id="sess-other", process_key="STRATEGIZE",
        )
        unrelated_pc = _seed_linked_path_claim(
            conn, work_claim_id=unrelated_process_claim,
        )
        conn.commit()

        result = release_claim(conn, item_claim_id, reason="released")

        assert result.get("linked_path_claim_ids") in (None, [])
        # Unrelated process path claim is undisturbed.
        unrelated_row = conn.execute(
            "SELECT state, released_at FROM path_claims WHERE id = %s",
            (unrelated_pc,),
        ).fetchone()
        assert unrelated_row["state"] == "active"
        assert unrelated_row["released_at"] is None

    def test_process_release_with_no_linked_paths_returns_empty_list(self, conn):
        work_claim_id = _seed_process_work_claim(
            conn, session_id=SESS, process_key="FEED",
        )
        conn.commit()

        result = release_claim(conn, work_claim_id, reason="released")

        assert result.get("linked_path_claim_ids") == []

    def test_item_release_clears_matching_current_item_id(self, conn):
        item_claim_id = _seed_item_work_claim(
            conn, session_id=SESS, item_id=50002,
        )
        conn.execute(
            "UPDATE harness_sessions SET current_item_id = %s, "
            "current_item_set_at = '2026-05-01T00:00:00Z' WHERE session_id = %s",
            ("50002", SESS),
        )
        conn.commit()

        release_claim(conn, item_claim_id, reason="released")

        row = conn.execute(
            "SELECT current_item_id, current_item_set_at, recent_item_id "
            "FROM harness_sessions WHERE session_id = %s",
            (SESS,),
        ).fetchone()
        assert row["current_item_id"] is None
        assert row["current_item_set_at"] is None
        assert row["recent_item_id"] == "50002"

    def test_item_release_leaves_unrelated_current_item_id_intact(self, conn):
        item_claim_id = _seed_item_work_claim(
            conn, session_id=SESS, item_id=50003,
        )
        conn.execute(
            "UPDATE harness_sessions SET current_item_id = %s, "
            "current_item_set_at = '2026-05-01T00:00:00Z' WHERE session_id = %s",
            ("99999", SESS),
        )
        conn.commit()

        release_claim(conn, item_claim_id, reason="released")

        row = conn.execute(
            "SELECT current_item_id FROM harness_sessions WHERE session_id = %s",
            (SESS,),
        ).fetchone()
        assert row["current_item_id"] == "99999"
