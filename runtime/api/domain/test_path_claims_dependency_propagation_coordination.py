"""Legacy-data repair on release for coord-only blocked rows.

Under the no-mutex contract, a downstream path claim can never land in
``state='blocked'`` solely because the only inter-item edge between
candidate and blocker is ``coordination_only`` — the overlap
classifier returns ``NONE`` for that shape and registration produces
``state='planned'`` instead. Rows that were written under the old
mutex semantics still need to drain when the upstream releases. This
file pins the release-propagation behavior against synthesized legacy
fixtures.

Each fixture forces ``state='blocked'`` by hand (mirroring the
historical write shape) and asserts that
:func:`propagate_release_unblock` flips the downstream to ``planned``
when only a coord-only sibling survives. A separate non-coord case
asserts the refresh-and-stay-blocked behavior is preserved for real
``activation`` edges.
"""

from __future__ import annotations

from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    add_edge,
    conn,
    count_refresh_events,
    seed_claim,
    seed_item,
    seed_target,
)
from yoke_core.domain.path_claims_dependency_propagation import (
    _blocked_reason_claim_id,
    propagate_release_unblock,
    unblock_stranded_for_released,
)

def _release(conn, claim_id: int):
    conn.execute(
        "UPDATE path_claims SET state = 'released', "
        "released_at = '2026-05-01T02:00:00Z', release_reason = 'test' "
        "WHERE id = %s",
        (claim_id,),
    )
    conn.commit()

class TestLegacyCoordinationOnlyRepair:
    """Legacy ``state='blocked'`` rows behind coord-only edges drain."""

    def test_release_repairs_coordination_only_blocked_row(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        a_item = seed_item(conn, item_id=4501)
        b_item = seed_item(conn, item_id=4502)
        a_claim = seed_claim(
            conn, item_id=a_item, target_id=target, state="active",
        )
        b_claim = seed_claim(
            conn, item_id=b_item, target_id=target, state="blocked",
            blocked_reason=f"path_claims.id={a_claim}",
        )
        add_edge(
            conn, dependent=b_item, blocking=a_item,
            gate_point="coordination_only",
        )
        _release(conn, a_claim)
        flipped = propagate_release_unblock(
            conn, released_claim_id=a_claim,
        )
        assert b_claim in flipped
        state, reason = conn.execute(
            "SELECT state, blocked_reason FROM path_claims WHERE id = %s",
            (b_claim,),
        ).fetchone()
        assert str(state) == "planned"
        assert reason is None

    def test_release_repairs_coord_only_with_surviving_sibling(self, conn):
        # AC-12 legacy data shape: A,B active; C blocked behind A; coord-only
        # edges between (B,C) and (A,C). After A releases, C must flip to
        # planned even though B is still active — the surviving sibling no
        # longer holds a mutex lane.
        target = seed_target(conn, path_string="runtime/api/domain")
        a_item = seed_item(conn, item_id=4601)
        b_item = seed_item(conn, item_id=4602)
        c_item = seed_item(conn, item_id=4603)
        a_claim = seed_claim(
            conn, item_id=a_item, target_id=target, state="active",
        )
        seed_claim(
            conn, item_id=b_item, target_id=target, state="active",
        )
        c_claim = seed_claim(
            conn, item_id=c_item, target_id=target, state="blocked",
            blocked_reason=f"path_claims.id={a_claim}",
        )
        add_edge(
            conn, dependent=c_item, blocking=a_item,
            gate_point="coordination_only",
        )
        add_edge(
            conn, dependent=c_item, blocking=b_item,
            gate_point="coordination_only",
        )
        _release(conn, a_claim)
        flipped = propagate_release_unblock(
            conn, released_claim_id=a_claim,
        )
        assert c_claim in flipped
        state, reason = conn.execute(
            "SELECT state, blocked_reason FROM path_claims WHERE id = %s",
            (c_claim,),
        ).fetchone()
        assert str(state) == "planned"
        assert reason is None


class TestIncompatibleOverlapStaysBlocked:
    """Path-mutex-only overlap (no dep edge) remains blocked at release."""

    def test_incompatible_overlap_keeps_blocked_with_refreshed_reason(self, conn):
        # The dep edge is the candidate's green light for path-claim
        # serialisation. Without an edge, the surviving overlap classifies
        # as ``INCOMPATIBLE`` and the candidate stays blocked, with the
        # refreshed ``blocked_reason`` pointing at the surviving sibling.
        target = seed_target(conn, path_string="runtime/api/domain")
        a_item = seed_item(conn, item_id=4701)
        b_item = seed_item(conn, item_id=4702)
        c_item = seed_item(conn, item_id=4703)
        a_claim = seed_claim(
            conn, item_id=a_item, target_id=target, state="active",
        )
        b_claim = seed_claim(
            conn, item_id=b_item, target_id=target, state="active",
        )
        c_claim = seed_claim(
            conn, item_id=c_item, target_id=target, state="blocked",
            blocked_reason=f"path_claims.id={a_claim}",
        )
        # No ``item_dependencies`` edges; the only overlap-survival
        # reason is path-mutex (real INCOMPATIBLE).
        _release(conn, a_claim)
        flipped = propagate_release_unblock(
            conn, released_claim_id=a_claim,
        )
        assert c_claim not in flipped
        state, reason = conn.execute(
            "SELECT state, blocked_reason FROM path_claims WHERE id = %s",
            (c_claim,),
        ).fetchone()
        assert str(state) == "blocked"
        assert _blocked_reason_claim_id(str(reason)) == b_claim


class TestSerialOverlapStaysBlocked:
    """Real dependency edges keep serial release propagation intact."""

    def test_activation_edge_refreshes_and_keeps_blocked(self, conn):
        # A releases, but B still overlaps C and has a real activation
        # edge to C. C must stay blocked and point at B; only
        # coord-only-only survivors are allowed to drain to planned.
        target = seed_target(conn, path_string="runtime/api/domain")
        a_item = seed_item(conn, item_id=4801)
        b_item = seed_item(conn, item_id=4802)
        c_item = seed_item(conn, item_id=4803)
        a_claim = seed_claim(
            conn, item_id=a_item, target_id=target, state="active",
        )
        b_claim = seed_claim(
            conn, item_id=b_item, target_id=target, state="active",
        )
        c_claim = seed_claim(
            conn, item_id=c_item, target_id=target, state="blocked",
            blocked_reason=f"path_claims.id={a_claim}",
        )
        add_edge(
            conn, dependent=c_item, blocking=b_item,
            gate_point="activation",
        )
        _release(conn, a_claim)

        before = count_refresh_events(conn, claim_id=c_claim)
        flipped = propagate_release_unblock(
            conn, released_claim_id=a_claim,
        )
        after = count_refresh_events(conn, claim_id=c_claim)

        assert c_claim not in flipped
        assert after - before == 1
        state, reason = conn.execute(
            "SELECT state, blocked_reason FROM path_claims WHERE id = %s",
            (c_claim,),
        ).fetchone()
        assert str(state) == "blocked"
        assert _blocked_reason_claim_id(str(reason)) == b_claim


class TestStrandedSweep:
    def test_unblock_stranded_idempotent_over_multiple_passes(self, conn):
        # AC-12 recovery surface: re-running the sweep does not double-emit
        # because the repaired row's blocked_reason is already cleared.
        target = seed_target(conn, path_string="runtime/api/domain")
        a_item = seed_item(conn, item_id=5001)
        b_item = seed_item(conn, item_id=5002)
        a_claim = seed_claim(
            conn, item_id=a_item, target_id=target, state="active",
        )
        b_claim = seed_claim(
            conn, item_id=b_item, target_id=target, state="blocked",
            blocked_reason=f"path_claims.id={a_claim}",
        )
        add_edge(
            conn, dependent=b_item, blocking=a_item,
            gate_point="coordination_only",
        )
        _release(conn, a_claim)
        before = count_refresh_events(conn, claim_id=b_claim)
        unblock_stranded_for_released(conn)
        unblock_stranded_for_released(conn)
        after = count_refresh_events(conn, claim_id=b_claim)
        # Repair flipped the row; no refresh event recorded.
        assert before == 0
        assert after == 0
        state = conn.execute(
            "SELECT state FROM path_claims WHERE id = %s", (b_claim,),
        ).fetchone()[0]
        assert str(state) == "planned"
