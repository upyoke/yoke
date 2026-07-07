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

import pytest

from yoke_core.domain.path_claims_dependency_propagation import (
    propagate_release_unblock,
    unblock_stranded_for_released,
)
from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    SNAP,
    conn,
    local_human,
    seed_target,
)


def _seed_item(conn, *, item_id: int, status: str = "implementing") -> int:
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', %s, 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (item_id, status, item_id),
    )
    conn.commit()
    return item_id


def _ensure_dep_table(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS item_dependencies ("
        "id INTEGER PRIMARY KEY, dependent_item TEXT NOT NULL, "
        "blocking_item TEXT NOT NULL, gate_point TEXT NOT NULL DEFAULT 'activation', "
        "satisfaction TEXT NOT NULL DEFAULT 'status:done', "
        "source TEXT NOT NULL, session_id INTEGER, "
        "rationale TEXT NOT NULL DEFAULT '', "
        "evidence_json TEXT NOT NULL DEFAULT '{}', "
        "created_at TEXT NOT NULL)"
    )
    conn.commit()


def _add_edge(conn, *, dependent: int, blocking: int,
              satisfaction: str = "status:done",
              gate_point: str = "activation"):
    _ensure_dep_table(conn)
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item, blocking_item, "
        "gate_point, satisfaction, source, created_at) "
        "VALUES (%s, %s, %s, %s, 'test', '2026-05-01T00:00:00Z')",
        (f"YOK-{dependent}", f"YOK-{blocking}", gate_point, satisfaction),
    )
    conn.commit()


def _seed_claim(
    conn, *, item_id: int, target_id: int, state: str,
    blocked_reason=None,
) -> int:
    actor = local_human(conn)
    row = conn.execute(
        "INSERT INTO path_claims "
        "(state, mode, actor_id, item_id, integration_target, registered_at, "
        "blocked_reason) "
        "VALUES (%s, 'exclusive', %s, %s, 'main', "
        "'2026-05-01T00:00:00Z', %s) RETURNING id",
        (state, actor, item_id, blocked_reason),
    ).fetchone()
    cid = int(row[0])
    if state == "active":
        conn.execute(
            "UPDATE path_claims SET activated_at = '2026-05-01T01:00:00Z', "
            "base_commit_sha = %s WHERE id = %s",
            (SNAP, cid),
        )
    conn.execute(
        "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
        "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
        (cid, target_id),
    )
    conn.commit()
    return cid


def _release_directly(conn, claim_id: int):
    conn.execute(
        "UPDATE path_claims SET state = 'released', "
        "released_at = '2026-05-01T02:00:00Z', release_reason = 'test' "
        "WHERE id = %s",
        (claim_id,),
    )
    conn.commit()


class TestDirectBlockedReasonUnblock:
    def test_downstream_unblocks_after_upstream_release(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        upstream_item = _seed_item(conn, item_id=4001)
        downstream_item = _seed_item(conn, item_id=4002)
        upstream_claim = _seed_claim(
            conn, item_id=upstream_item, target_id=target, state="active",
        )
        downstream_claim = _seed_claim(
            conn, item_id=downstream_item, target_id=target,
            state="blocked",
            blocked_reason=f"serial-via-dependency on path_claims.id={upstream_claim}",
        )
        _release_directly(conn, upstream_claim)
        flipped = propagate_release_unblock(
            conn, released_claim_id=upstream_claim,
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
            conn, item_id=released_item, target_id=target, state="active",
        )
        for offset in range(8):
            filler_item = _seed_item(conn, item_id=4060 + offset)
            _seed_claim(
                conn, item_id=filler_item, target_id=target,
                state="released",
            )
        other_claim = _seed_claim(
            conn, item_id=other_item, target_id=target, state="active",
        )
        downstream_claim = _seed_claim(
            conn, item_id=downstream_item, target_id=target,
            state="blocked",
            blocked_reason=(
                f"serial-via-dependency on path_claims.id={other_claim}"
            ),
        )

        _release_directly(conn, released_claim)
        flipped = propagate_release_unblock(
            conn, released_claim_id=released_claim,
        )

        assert other_claim == 10
        assert downstream_claim not in flipped


class TestDepGraphSatisfactionUnblock:
    def test_unrelated_downstream_unblocks_via_dep_satisfaction(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        upstream_item = _seed_item(
            conn, item_id=4101, status="done",  # already satisfied
        )
        downstream_item = _seed_item(
            conn, item_id=4102, status="implementing",
        )
        # Downstream is blocked by an unrelated claim, but the dep edge
        # to upstream_item is now satisfied (its status is 'done').
        unrelated_target = seed_target(conn, path_string="docs")
        unrelated_claim = _seed_claim(
            conn, item_id=upstream_item, target_id=unrelated_target,
            state="active",
        )
        downstream_claim = _seed_claim(
            conn, item_id=downstream_item, target_id=target,
            state="blocked",
            blocked_reason=f"serial-via-dependency on path_claims.id={unrelated_claim}",
        )
        _add_edge(conn, dependent=downstream_item, blocking=upstream_item)
        _release_directly(conn, unrelated_claim)
        flipped = propagate_release_unblock(
            conn, released_claim_id=unrelated_claim,
        )
        assert downstream_claim in flipped


class TestSurvivingOverlapStaysBlocked:
    def test_downstream_stays_blocked_when_overlap_persists(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        a_item = _seed_item(conn, item_id=4201)
        b_item = _seed_item(conn, item_id=4202)
        downstream_item = _seed_item(conn, item_id=4203)
        a_claim = _seed_claim(
            conn, item_id=a_item, target_id=target, state="active",
        )
        # B claim still active on the same target — releasing A should
        # NOT unblock the downstream because B still holds the door lock.
        _seed_claim(
            conn, item_id=b_item, target_id=target, state="active",
        )
        downstream_claim = _seed_claim(
            conn, item_id=downstream_item, target_id=target,
            state="blocked",
            blocked_reason=f"serial-via-dependency on path_claims.id={a_claim}",
        )
        _release_directly(conn, a_claim)
        flipped = propagate_release_unblock(
            conn, released_claim_id=a_claim,
        )
        assert downstream_claim not in flipped
        new_state = conn.execute(
            "SELECT state FROM path_claims WHERE id = %s",
            (downstream_claim,),
        ).fetchone()[0]
        assert str(new_state) == "blocked"


def _seed_serial_via_dep_scenario(conn, *, base_item_id: int, sibling_count: int):
    """Blocked downstream with sibling overlaps sanctioned by dep edges."""
    target = seed_target(conn, path_string="runtime/api/domain")
    upstream_item = _seed_item(conn, item_id=base_item_id)
    downstream_item = _seed_item(conn, item_id=base_item_id + 1)
    upstream_claim = _seed_claim(
        conn, item_id=upstream_item, target_id=target, state="active",
    )
    for offset in range(sibling_count):
        sibling_item = _seed_item(conn, item_id=base_item_id + 2 + offset)
        _seed_claim(
            conn, item_id=sibling_item, target_id=target, state="active",
        )
        _add_edge(conn, dependent=sibling_item, blocking=downstream_item)
    downstream_claim = _seed_claim(
        conn, item_id=downstream_item, target_id=target, state="blocked",
        blocked_reason=(
            f"serial-via-dependency on path_claims.id={upstream_claim}"
        ),
    )
    _release_directly(conn, upstream_claim)
    return upstream_claim, downstream_claim


def _assert_flipped_to_planned(conn, downstream_claim: int, flipped):
    assert downstream_claim in flipped
    state, reason = conn.execute(
        "SELECT state, blocked_reason FROM path_claims WHERE id = %s",
        (downstream_claim,),
    ).fetchone()
    assert str(state) == "planned"
    assert reason is None


class TestSerialViaDependencyUnblock:
    def test_downstream_unblocks_when_remaining_overlap_is_dep_sanctioned(
        self, conn,
    ):
        upstream_claim, downstream_claim = _seed_serial_via_dep_scenario(
            conn, base_item_id=4401, sibling_count=2,
        )
        flipped = propagate_release_unblock(
            conn, released_claim_id=upstream_claim,
        )
        _assert_flipped_to_planned(conn, downstream_claim, flipped)

    def test_unblock_stranded_recovery_inherits_widened_acceptance(
        self, conn,
    ):
        upstream_claim, downstream_claim = _seed_serial_via_dep_scenario(
            conn, base_item_id=4451, sibling_count=1,
        )
        flipped = unblock_stranded_for_released(
            conn, claim_id=upstream_claim,
        )
        _assert_flipped_to_planned(conn, downstream_claim, flipped)


class TestIdempotency:
    def test_repeated_propagation_is_safe(self, conn):
        target = seed_target(conn, path_string="runtime/api/domain")
        upstream_item = _seed_item(conn, item_id=4301)
        downstream_item = _seed_item(conn, item_id=4302)
        upstream_claim = _seed_claim(
            conn, item_id=upstream_item, target_id=target, state="active",
        )
        _seed_claim(
            conn, item_id=downstream_item, target_id=target,
            state="blocked",
            blocked_reason=f"serial-via-dependency on path_claims.id={upstream_claim}",
        )
        _release_directly(conn, upstream_claim)
        first = propagate_release_unblock(
            conn, released_claim_id=upstream_claim,
        )
        second = propagate_release_unblock(
            conn, released_claim_id=upstream_claim,
        )
        assert first  # downstream was flipped
        assert second == []  # second pass finds nothing to flip
