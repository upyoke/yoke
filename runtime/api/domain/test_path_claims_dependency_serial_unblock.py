# ruff: noqa: F811
"""Release propagation when remaining overlaps are dependency-sanctioned."""

from runtime.api.domain._path_claims_test_helpers import conn, seed_target  # noqa: F401
from yoke_core.domain.path_claims_dependency_propagation import (
    propagate_release_unblock,
    unblock_stranded_for_released,
)
from runtime.api.domain.test_path_claims_dependency_propagation import (
    _add_edge,
    _release_directly,
    _seed_claim,
    _seed_item,
)


def _seed_serial_via_dep_scenario(conn, *, base_item_id: int, sibling_count: int):
    target = seed_target(conn, path_string="runtime/api/domain")
    upstream_item = _seed_item(conn, item_id=base_item_id)
    downstream_item = _seed_item(conn, item_id=base_item_id + 1)
    upstream_claim = _seed_claim(
        conn,
        item_id=upstream_item,
        target_id=target,
        state="active",
    )
    for offset in range(sibling_count):
        sibling_item = _seed_item(conn, item_id=base_item_id + 2 + offset)
        _seed_claim(
            conn,
            item_id=sibling_item,
            target_id=target,
            state="active",
        )
        _add_edge(conn, dependent=sibling_item, blocking=downstream_item)
    downstream_claim = _seed_claim(
        conn,
        item_id=downstream_item,
        target_id=target,
        state="blocked",
        blocked_reason=f"serial-via-dependency on path_claims.id={upstream_claim}",
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
        self,
        conn,
    ):
        upstream_claim, downstream_claim = _seed_serial_via_dep_scenario(
            conn,
            base_item_id=4401,
            sibling_count=2,
        )
        flipped = propagate_release_unblock(
            conn,
            released_claim_id=upstream_claim,
        )
        _assert_flipped_to_planned(conn, downstream_claim, flipped)

    def test_unblock_stranded_recovery_inherits_widened_acceptance(
        self,
        conn,
    ):
        upstream_claim, downstream_claim = _seed_serial_via_dep_scenario(
            conn,
            base_item_id=4451,
            sibling_count=1,
        )
        flipped = unblock_stranded_for_released(
            conn,
            claim_id=upstream_claim,
        )
        _assert_flipped_to_planned(conn, downstream_claim, flipped)
