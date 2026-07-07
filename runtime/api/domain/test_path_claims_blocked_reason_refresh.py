"""Focused helper tests for :mod:`path_claims_blocked_reason_refresh`.

Split out of ``test_path_claims_dependency_propagation_coordination.py`` so
the propagation-coordination file stays under the 350-line cap and these
edge-change wording tests live next to the helper they exercise.

Covers AC-1/2/3/4/5/6: every direction of ``item_dependencies`` edge change
between a candidate and a blocker recomputes wording on the candidate's
``state='blocked'`` row to reflect the *current* edge shape, while state
is preserved. ``cause='item_dependency_edge_change'`` distinguishes this
refresh from the upstream-release path.
"""

from __future__ import annotations

import json

from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    add_edge,
    conn,
    count_refresh_events,
    seed_claim,
    seed_item,
    seed_target,
)
from yoke_core.domain.path_claims_blocked_reason_refresh import (
    refresh_blocked_reason_for_edge_change,
)

class TestEdgeChangeRefresh:
    """Wording-only refresh after item_dependencies edge-type change.

    Covers AC-1/2/3/5/6: when the dep edge between two items changes
    (UPDATE to coordination_only, DELETE, or INSERT that introduces a
    serial edge), every non-terminal blocked row whose upstream pointer
    references a claim owned by either party has its blocked_reason
    rewritten to reflect the current edge shape. The refresh is
    wording-only — state stays ``blocked`` (state repair lives in
    ``path_claims_blocked_coordination_repair``). A
    ``PathClaimBlockedReasonRefreshed`` event with
    ``cause='item_dependency_edge_change'`` records each rewrite.
    """

    def _seed_three_item_overlap(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        a_item = seed_item(conn, item_id=5101)
        b_item = seed_item(conn, item_id=5102)
        c_item = seed_item(conn, item_id=5103)
        a_claim = seed_claim(
            conn, item_id=a_item, target_id=target, state="active",
        )
        b_claim = seed_claim(
            conn, item_id=b_item, target_id=target, state="active",
        )
        c_claim = seed_claim(
            conn, item_id=c_item, target_id=target, state="blocked",
            blocked_reason=f"serial-via-dependency on path_claims.id={a_claim}",
        )
        return {
            "a_item": a_item, "a_claim": a_claim,
            "b_item": b_item, "b_claim": b_claim,
            "c_item": c_item, "c_claim": c_claim,
        }

    def _last_refresh_event(self, conn, *, claim_id):
        rows = conn.execute(
            "SELECT envelope FROM events "
            "WHERE event_name = 'PathClaimBlockedReasonRefreshed' "
            "ORDER BY id DESC"
        ).fetchall()
        for row in rows:
            envelope = json.loads(row["envelope"])
            if envelope["context"]["claim_id"] == claim_id:
                return row["envelope"]
        return None

    def test_activation_to_coordination_only_rewrites_to_path_mutex(self, conn):
        # AC-6(a): hard activation demoted to coordination_only. C was
        # blocked behind A. After the UPDATE, A-C is coord_only (no
        # serial), but B still overlaps C with no edge — path-mutex.
        seeded = self._seed_three_item_overlap(conn)
        add_edge(
            conn, dependent=seeded["c_item"], blocking=seeded["a_item"],
            gate_point="activation",
        )
        conn.execute(
            "UPDATE item_dependencies SET gate_point='coordination_only' "
            "WHERE dependent_item=%s AND blocking_item=%s",
            (f"YOK-{seeded['c_item']}", f"YOK-{seeded['a_item']}"),
        )
        conn.commit()
        refreshed = refresh_blocked_reason_for_edge_change(
            conn,
            dependent_item_id=seeded["c_item"],
            blocking_item_id=seeded["a_item"],
        )
        assert seeded["c_claim"] in refreshed
        state, reason = conn.execute(
            "SELECT state, blocked_reason FROM path_claims WHERE id = %s",
            (seeded["c_claim"],),
        ).fetchone()
        assert str(state) == "blocked"
        assert str(reason) == f"path-mutex on path_claims.id={seeded['b_claim']}"
        envelope = self._last_refresh_event(conn, claim_id=seeded["c_claim"])
        assert envelope is not None
        ctx = json.loads(envelope)["context"]
        assert ctx["cause"] == "item_dependency_edge_change"
        assert ctx["dependent_item_id"] == seeded["c_item"]
        assert ctx["blocking_item_id"] == seeded["a_item"]

    def test_coordination_only_delete_keeps_path_mutex_wording(self, conn):
        # AC-6(b): coord_only edge DELETED. After deletion both A and B
        # overlap C with no edge (real INCOMPATIBLE). The refresh picks
        # the lowest-id overlap as the canonical "path-mutex on X" peer.
        seeded = self._seed_three_item_overlap(conn)
        add_edge(
            conn, dependent=seeded["c_item"], blocking=seeded["a_item"],
            gate_point="coordination_only",
        )
        conn.execute(
            "DELETE FROM item_dependencies "
            "WHERE dependent_item=%s AND blocking_item=%s",
            (f"YOK-{seeded['c_item']}", f"YOK-{seeded['a_item']}"),
        )
        conn.commit()
        refreshed = refresh_blocked_reason_for_edge_change(
            conn,
            dependent_item_id=seeded["c_item"],
            blocking_item_id=seeded["a_item"],
        )
        assert seeded["c_claim"] in refreshed
        state, reason = conn.execute(
            "SELECT state, blocked_reason FROM path_claims WHERE id = %s",
            (seeded["c_claim"],),
        ).fetchone()
        assert str(state) == "blocked"
        valid = {
            f"path-mutex on path_claims.id={seeded['a_claim']}",
            f"path-mutex on path_claims.id={seeded['b_claim']}",
        }
        assert str(reason) in valid

    def test_activation_delete_rewrites_to_path_mutex(self, conn):
        # AC-6(c): activation edge DELETED. Same shape as (b) — both
        # surviving overlaps have no edge. Wording rotation from
        # "serial-via-dep" to "path-mutex" is the load-bearing assertion.
        seeded = self._seed_three_item_overlap(conn)
        add_edge(
            conn, dependent=seeded["c_item"], blocking=seeded["a_item"],
            gate_point="activation",
        )
        conn.execute(
            "DELETE FROM item_dependencies "
            "WHERE dependent_item=%s AND blocking_item=%s",
            (f"YOK-{seeded['c_item']}", f"YOK-{seeded['a_item']}"),
        )
        conn.commit()
        refreshed = refresh_blocked_reason_for_edge_change(
            conn,
            dependent_item_id=seeded["c_item"],
            blocking_item_id=seeded["a_item"],
        )
        assert seeded["c_claim"] in refreshed
        reason = conn.execute(
            "SELECT blocked_reason FROM path_claims WHERE id = %s",
            (seeded["c_claim"],),
        ).fetchone()[0]
        assert str(reason).startswith("path-mutex on path_claims.id=")
        state = conn.execute(
            "SELECT state FROM path_claims WHERE id = %s",
            (seeded["c_claim"],),
        ).fetchone()[0]
        assert str(state) == "blocked"

    def test_coordination_only_to_activation_rewrites_to_serial(self, conn):
        # AC-6(d): re-tightening — coord_only becomes activation. Only A
        # overlaps C, so classifier returns SERIAL_VIA_DEPENDENCY and the
        # wording rotates to "serial-via-dependency on path_claims.id=A".
        target = seed_target(conn, path_string="runtime/api/domain")
        a_item = seed_item(conn, item_id=5301)
        c_item = seed_item(conn, item_id=5302)
        a_claim = seed_claim(
            conn, item_id=a_item, target_id=target, state="active",
        )
        c_claim = seed_claim(
            conn, item_id=c_item, target_id=target, state="blocked",
            blocked_reason=f"path-mutex on path_claims.id={a_claim}",
        )
        add_edge(
            conn, dependent=c_item, blocking=a_item,
            gate_point="activation",
        )
        refreshed = refresh_blocked_reason_for_edge_change(
            conn, dependent_item_id=c_item, blocking_item_id=a_item,
        )
        assert c_claim in refreshed
        reason = conn.execute(
            "SELECT blocked_reason FROM path_claims WHERE id = %s",
            (c_claim,),
        ).fetchone()[0]
        assert str(reason) == (
            f"serial-via-dependency on path_claims.id={a_claim}"
        )

    def test_refresh_skips_when_overlap_is_none(self, conn):
        # When path mutex is no longer real (NONE), refresh skips
        # and lets the coord-only repair pass handle state.
        target = seed_target(conn, path_string="runtime/api/domain")
        a_item = seed_item(conn, item_id=5201)
        c_item = seed_item(conn, item_id=5202)
        a_claim = seed_claim(
            conn, item_id=a_item, target_id=target, state="released",
        )
        c_claim = seed_claim(
            conn, item_id=c_item, target_id=target, state="blocked",
            blocked_reason=f"serial-via-dependency on path_claims.id={a_claim}",
        )
        before = count_refresh_events(conn, claim_id=c_claim)
        refresh_blocked_reason_for_edge_change(
            conn, dependent_item_id=c_item, blocking_item_id=a_item,
        )
        after = count_refresh_events(conn, claim_id=c_claim)
        assert after == before
        reason = conn.execute(
            "SELECT blocked_reason FROM path_claims WHERE id = %s",
            (c_claim,),
        ).fetchone()[0]
        assert str(reason) == (
            f"serial-via-dependency on path_claims.id={a_claim}"
        )

    def test_refresh_is_idempotent_when_wording_unchanged(self, conn):
        # Running the refresh twice produces no second event when the
        # recomputed wording matches the prior.
        seeded = self._seed_three_item_overlap(conn)
        add_edge(
            conn, dependent=seeded["c_item"], blocking=seeded["a_item"],
            gate_point="coordination_only",
        )
        before = count_refresh_events(conn, claim_id=seeded["c_claim"])
        refresh_blocked_reason_for_edge_change(
            conn,
            dependent_item_id=seeded["c_item"],
            blocking_item_id=seeded["a_item"],
        )
        mid = count_refresh_events(conn, claim_id=seeded["c_claim"])
        refresh_blocked_reason_for_edge_change(
            conn,
            dependent_item_id=seeded["c_item"],
            blocking_item_id=seeded["a_item"],
        )
        after = count_refresh_events(conn, claim_id=seeded["c_claim"])
        assert mid - before == 1
        assert after == mid
