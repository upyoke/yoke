# ruff: noqa: F811
"""Coverage for the post-release dep-graph propagation.

When ``path_claims.release`` flips a claim to ``state='released'``,
``propagate_release_unblock`` re-evaluates downstream blocked claims
via:

* direct ``blocked_reason='path_claims.id=N'`` references, and
* ``item_dependencies`` satisfaction (``status:done`` predicate, etc.).

Claims that no longer have a real conflict transition
``blocked → planned`` with cleared ``blocked_reason``. Surviving
overlap keeps the claim blocked.
"""

from __future__ import annotations

from runtime.api.domain.path_claims_dependency_propagation_test_support import (
    _add_edge as _add_edge,
    _ensure_dep_table as _ensure_dep_table,
    _release_directly as _release_directly,
    _seed_claim as _seed_claim,
    _seed_item as _seed_item,
)


from yoke_core.domain.path_claims_dependency_propagation import (
    propagate_release_unblock,
)
from runtime.api.domain._path_claims_test_helpers import (  # noqa: F401
    SNAP,
    conn,
    local_human,
    seed_target,
)


class TestDirectBlockedReasonUnblock:
    def test_downstream_unblocks_after_upstream_release(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        upstream_item = _seed_item(conn, item_id=4001)
        downstream_item = _seed_item(conn, item_id=4002)
        upstream_claim = _seed_claim(
            conn,
            item_id=upstream_item,
            target_id=target,
            state="active",
        )
        downstream_claim = _seed_claim(
            conn,
            item_id=downstream_item,
            target_id=target,
            state="blocked",
            blocked_reason=f"serial-via-dependency on path_claims.id={upstream_claim}",
        )
        _release_directly(conn, upstream_claim)
        flipped = propagate_release_unblock(
            conn,
            released_claim_id=upstream_claim,
        )
        assert downstream_claim in flipped
        new_state = conn.execute(
            "SELECT state, blocked_reason FROM path_claims WHERE id = %s",
            (downstream_claim,),
        ).fetchone()
        assert str(new_state[0]) == "planned"
        assert new_state[1] is None

    def test_direct_reason_matches_exact_claim_id(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        released_item = _seed_item(conn, item_id=4051)
        other_item = _seed_item(conn, item_id=4052)
        downstream_item = _seed_item(conn, item_id=4053)
        released_claim = _seed_claim(
            conn,
            item_id=released_item,
            target_id=target,
            state="active",
        )
        for offset in range(8):
            filler_item = _seed_item(conn, item_id=4060 + offset)
            _seed_claim(
                conn,
                item_id=filler_item,
                target_id=target,
                state="released",
            )
        other_claim = _seed_claim(
            conn,
            item_id=other_item,
            target_id=target,
            state="active",
        )
        downstream_claim = _seed_claim(
            conn,
            item_id=downstream_item,
            target_id=target,
            state="blocked",
            blocked_reason=(f"serial-via-dependency on path_claims.id={other_claim}"),
        )

        _release_directly(conn, released_claim)
        flipped = propagate_release_unblock(
            conn,
            released_claim_id=released_claim,
        )

        assert other_claim == 10
        assert downstream_claim not in flipped

    def test_terminal_downstream_is_not_resurrected(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        upstream_item = _seed_item(conn, item_id=4081)
        downstream_item = _seed_item(
            conn,
            item_id=4082,
            status="done",
        )
        upstream_claim = _seed_claim(
            conn,
            item_id=upstream_item,
            target_id=target,
            state="active",
        )
        downstream_claim = _seed_claim(
            conn,
            item_id=downstream_item,
            target_id=target,
            state="blocked",
            blocked_reason=(
                f"serial-via-dependency on path_claims.id={upstream_claim}"
            ),
        )
        _release_directly(conn, upstream_claim)

        assert (
            propagate_release_unblock(
                conn,
                released_claim_id=upstream_claim,
            )
            == []
        )
        state = conn.execute(
            "SELECT state FROM path_claims WHERE id=%s",
            (downstream_claim,),
        ).fetchone()[0]
        assert str(state) == "blocked"


class TestDepGraphSatisfactionUnblock:
    def test_unrelated_downstream_unblocks_via_dep_satisfaction(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        upstream_item = _seed_item(
            conn,
            item_id=4101,
            status="done",  # already satisfied
        )
        downstream_item = _seed_item(
            conn,
            item_id=4102,
            status="implementing",
        )
        # Downstream is blocked by an unrelated claim, but the dep edge
        # to upstream_item is now satisfied (its status is 'done').
        unrelated_target = seed_target(conn, path_string="docs")
        unrelated_claim = _seed_claim(
            conn,
            item_id=upstream_item,
            target_id=unrelated_target,
            state="active",
        )
        downstream_claim = _seed_claim(
            conn,
            item_id=downstream_item,
            target_id=target,
            state="blocked",
            blocked_reason=f"serial-via-dependency on path_claims.id={unrelated_claim}",
        )
        _add_edge(conn, dependent=downstream_item, blocking=upstream_item)
        _release_directly(conn, unrelated_claim)
        flipped = propagate_release_unblock(
            conn,
            released_claim_id=unrelated_claim,
        )
        assert downstream_claim in flipped


class TestSurvivingOverlapStaysBlocked:
    def test_downstream_stays_blocked_when_overlap_persists(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        a_item = _seed_item(conn, item_id=4201)
        b_item = _seed_item(conn, item_id=4202)
        downstream_item = _seed_item(conn, item_id=4203)
        a_claim = _seed_claim(
            conn,
            item_id=a_item,
            target_id=target,
            state="active",
        )
        # B claim still active on the same target — releasing A should
        # NOT unblock the downstream because B still holds the door lock.
        _seed_claim(
            conn,
            item_id=b_item,
            target_id=target,
            state="active",
        )
        downstream_claim = _seed_claim(
            conn,
            item_id=downstream_item,
            target_id=target,
            state="blocked",
            blocked_reason=f"serial-via-dependency on path_claims.id={a_claim}",
        )
        _release_directly(conn, a_claim)
        flipped = propagate_release_unblock(
            conn,
            released_claim_id=a_claim,
        )
        assert downstream_claim not in flipped
        new_state = conn.execute(
            "SELECT state FROM path_claims WHERE id = %s",
            (downstream_claim,),
        ).fetchone()[0]
        assert str(new_state) == "blocked"


class TestIdempotency:
    def test_repeated_propagation_is_safe(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        upstream_item = _seed_item(conn, item_id=4301)
        downstream_item = _seed_item(conn, item_id=4302)
        upstream_claim = _seed_claim(
            conn,
            item_id=upstream_item,
            target_id=target,
            state="active",
        )
        _seed_claim(
            conn,
            item_id=downstream_item,
            target_id=target,
            state="blocked",
            blocked_reason=f"serial-via-dependency on path_claims.id={upstream_claim}",
        )
        _release_directly(conn, upstream_claim)
        first = propagate_release_unblock(
            conn,
            released_claim_id=upstream_claim,
        )
        second = propagate_release_unblock(
            conn,
            released_claim_id=upstream_claim,
        )
        assert first  # downstream was flipped
        assert second == []  # second pass finds nothing to flip
