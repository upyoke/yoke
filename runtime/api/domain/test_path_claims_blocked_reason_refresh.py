# ruff: noqa: F811

"""Dependency changes release eligible reservations and refresh surviving blockers."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.item_dependency import cmd_dependency_update

from runtime.api.domain._path_claims_test_helpers import (  # noqa: F401
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
    def _seed_three_item_overlap(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        a_item = seed_item(conn, item_id=5101)
        b_item = seed_item(conn, item_id=5102)
        c_item = seed_item(conn, item_id=5103)
        a_claim = seed_claim(
            conn,
            item_id=a_item,
            target_id=target,
            state="active",
        )
        b_claim = seed_claim(
            conn,
            item_id=b_item,
            target_id=target,
            state="active",
        )
        c_claim = seed_claim(
            conn,
            item_id=c_item,
            target_id=target,
            state="blocked",
            blocked_reason=f"serial-via-dependency on path_claims.id={a_claim}",
        )
        return {
            "a_item": a_item,
            "a_claim": a_claim,
            "b_item": b_item,
            "b_claim": b_claim,
            "c_item": c_item,
            "c_claim": c_claim,
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
        # Hard activation demoted to coordination_only. C was
        # blocked behind A. After the UPDATE, A-C is coord_only (no
        # serial), but B still overlaps C with no edge — path-mutex.
        seeded = self._seed_three_item_overlap(conn)
        add_edge(
            conn,
            dependent=seeded["c_item"],
            blocking=seeded["a_item"],
            gate_point="activation",
        )
        conn.execute(
            "UPDATE item_dependencies SET gate_point='coordination_only' "
            "WHERE dependent_item_id=%s AND blocking_item_id=%s",
            (seeded["c_item"], seeded["a_item"]),
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
        # The coord_only edge is DELETED. After deletion both A and B
        # overlap C with no edge (real INCOMPATIBLE). The refresh picks
        # the lowest-id overlap as the canonical "path-mutex on X" peer.
        seeded = self._seed_three_item_overlap(conn)
        add_edge(
            conn,
            dependent=seeded["c_item"],
            blocking=seeded["a_item"],
            gate_point="coordination_only",
        )
        conn.execute(
            "DELETE FROM item_dependencies "
            "WHERE dependent_item_id=%s AND blocking_item_id=%s",
            (seeded["c_item"], seeded["a_item"]),
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
        # Activation edge DELETED. Same shape as the delete above — both
        # surviving overlaps have no edge. Wording rotation from
        # "serial-via-dep" to "path-mutex" is the load-bearing assertion.
        seeded = self._seed_three_item_overlap(conn)
        add_edge(
            conn,
            dependent=seeded["c_item"],
            blocking=seeded["a_item"],
            gate_point="activation",
        )
        conn.execute(
            "DELETE FROM item_dependencies "
            "WHERE dependent_item_id=%s AND blocking_item_id=%s",
            (seeded["c_item"], seeded["a_item"]),
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
        # Re-tightening — coord_only becomes activation. Only A
        # overlaps C, so classifier returns SERIAL_VIA_DEPENDENCY and the
        # wording rotates to "serial-via-dependency on path_claims.id=A".
        target = seed_target(conn, path_string="runtime/api/domain")
        a_item = seed_item(conn, item_id=5301)
        c_item = seed_item(conn, item_id=5302)
        a_claim = seed_claim(
            conn,
            item_id=a_item,
            target_id=target,
            state="active",
        )
        c_claim = seed_claim(
            conn,
            item_id=c_item,
            target_id=target,
            state="blocked",
            blocked_reason=f"path-mutex on path_claims.id={a_claim}",
        )
        add_edge(
            conn,
            dependent=c_item,
            blocking=a_item,
            gate_point="activation",
        )
        refreshed = refresh_blocked_reason_for_edge_change(
            conn,
            dependent_item_id=c_item,
            blocking_item_id=a_item,
        )
        assert c_claim in refreshed
        reason = conn.execute(
            "SELECT blocked_reason FROM path_claims WHERE id = %s",
            (c_claim,),
        ).fetchone()[0]
        assert str(reason) == (f"serial-via-dependency on path_claims.id={a_claim}")

    @pytest.mark.parametrize("item_status", ["idea", "done"])
    def test_dependency_demotion_releases_only_live_item_claim(self, conn, item_status):
        target = seed_target(conn, path_string="runtime/api/domain")
        upstream = seed_item(conn, item_id=5201)
        dependent = seed_item(conn, item_id=5202, status=item_status)
        upstream_claim = seed_claim(
            conn,
            item_id=upstream,
            target_id=target,
            state="active",
        )
        reason = f"serial-via-dependency on path_claims.id={upstream_claim}"
        claim = seed_claim(
            conn,
            item_id=dependent,
            target_id=target,
            state="blocked",
            blocked_reason=reason,
        )
        add_edge(conn, dependent=dependent, blocking=upstream, gate_point="activation")
        cmd_dependency_update(
            conn,
            dependent=f"YOK-{dependent}",
            blocking=f"YOK-{upstream}",
            match_gate_point="activation",
            gate_point="coordination_only",
        )
        row = conn.execute(
            "SELECT state, blocked_reason FROM path_claims WHERE id=%s",
            (claim,),
        ).fetchone()
        expected = ("planned", None) if item_status == "idea" else ("blocked", reason)
        assert tuple(row) == expected
        assert (
            refresh_blocked_reason_for_edge_change(
                conn,
                dependent_item_id=dependent,
                blocking_item_id=upstream,
            )
            == []
        )

    def test_refresh_is_idempotent_when_wording_unchanged(self, conn):
        # Running the refresh twice produces no second event when the
        # recomputed wording matches the prior.
        seeded = self._seed_three_item_overlap(conn)
        add_edge(
            conn,
            dependent=seeded["c_item"],
            blocking=seeded["a_item"],
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
