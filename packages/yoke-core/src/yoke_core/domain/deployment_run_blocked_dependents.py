"""Members whose hard-block blocker does not ship with them wait for a later release.

Carried enrollment skips a candidate whose blocker neither ships in the same
run nor has shipped (:mod:`deployment_run_carried_enrollment`). Two paths put
members into a run without that skip: a takeover moves the older run's
unfinished members, and a start sets reworking members aside while their
dependents stay. Either leaves a member whose blocker is absent, and
composition's dependency check then refuses the whole run.

Both paths now leave such a member out the way a reworking member is set
aside: its membership is removed with :data:`BLOCKED_SET_ASIDE_REASON` and
its QA preserved, so the first release after the blocker ships enrolls it and
adopts that QA. The composition notice names it beside the other skipped
carried items.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from yoke_core.domain.deployment_run_dependency_readiness import (
    unshipped_dependency_pairs,
)
from yoke_core.domain.deployment_run_landed_closeout import flag_frozen_item_ids
from yoke_core.domain.item_ref_render import render_item_ref_lookup

BLOCKED_SET_ASIDE_REASON = (
    "hard-block blocker does not ship in this run; awaiting enrollment in the "
    "first release after it ships"
)


def blocked_members(
    conn: Any, item_ids: Iterable[int], *, shipping: Iterable[int] = ()
) -> dict[int, int]:
    """Each of *item_ids* whose blocker neither ships here nor has shipped.

    *item_ids* ship together with *shipping*; holding one back can strand its
    own dependents, so the set shrinks until it is stable. Returns each held
    member and one blocker it waits on.
    """
    ids = sorted({int(item_id) for item_id in item_ids})
    pairs = unshipped_dependency_pairs(conn, ids, member_ids=shipping)
    return {int(dependent): int(blocker) for dependent, blocker, _ in pairs}


def takeover_shipping(
    conn: Any, moving: Iterable[int], members: Iterable[int]
) -> set[int]:
    """What ships beside members a takeover moves, before carried enrollment.

    Takeover runs before the carried pass enrolls this run's new work, so a
    blocker that pass will admit is not a member yet. A landed blocker at its
    release stage that no other live release holds is admitted beside its
    dependents and counts as shipping. Should it not be admitted after all,
    composition's dependency check refuses the run and names it.
    """
    from yoke_core.domain.deployment_run_dependency_readiness import (
        blocker_holding_run,
    )
    from yoke_core.domain.workflow_delivery_binding_validation import (
        delivery_ready_for_stage,
    )
    from yoke_core.domain.workflow_item_binding_validation import read_pinned_items

    shipping = {int(item_id) for item_id in members}
    ids = sorted({int(item_id) for item_id in moving})
    if not ids:
        return shipping
    rows = conn.execute(
        "SELECT DISTINCT d.blocking_item_id FROM item_dependencies d "
        "JOIN items b ON b.id=d.blocking_item_id "
        "WHERE d.dependent_item_id=ANY(%s) "
        "AND COALESCE(b.merge_queue_landed_at,b.merged_at) IS NOT NULL",
        (ids,),
    ).fetchall()
    landed = {int(row[0]) for row in rows} - set(ids) - shipping
    landed -= flag_frozen_item_ids(conn, landed)
    for item_id, item in read_pinned_items(conn, landed).items():
        runtime = item.require_runtime(conn, item_id)
        if (
            item.status not in runtime.terminal_stage_ids
            and delivery_ready_for_stage(runtime, item.status)
            and blocker_holding_run(conn, item_id) is None
        ):
            shipping.add(int(item_id))
    return shipping


def dependents_stranded_by(
    conn: Any, roots: Iterable[int], remaining: Iterable[int]
) -> dict[int, int]:
    """Members of *remaining* that, once *roots* leave, wait on an absent blocker.

    Only chains that lead back to *roots* count, so an edge the run was
    already carrying, such as a pending pair merge, is left alone.
    """
    reached = {int(root) for root in roots}
    held = blocked_members(conn, remaining)
    stranded: dict[int, int] = {}
    while True:
        new = {
            dependent: blocker
            for dependent, blocker in held.items()
            if blocker in reached and dependent not in reached
        }
        if not new:
            return stranded
        stranded.update(new)
        reached.update(new)


def set_aside_blocked_members(
    conn: Any,
    run_id: str,
    blocked: dict[int, int],
    *,
    session_id: str | None = None,
    actor_id: int | None = None,
) -> dict[int, str]:
    """Remove *blocked* members from *run_id*, keeping their QA for later.

    The caller holds the run lock and owns the transaction.
    """
    from yoke_core.domain.deployment_run_member_removal import remove_members_on

    if not blocked:
        return {}
    return remove_members_on(
        conn,
        run_id,
        blocked,
        reason=BLOCKED_SET_ASIDE_REASON,
        session_id=session_id,
        actor_id=actor_id,
        removed_by="blocker not shipping",
        preserve_qa=True,
    )


def left_by_takeover(conn: Any, run_id: str) -> dict[int, tuple[int, str]]:
    """Members a takeover by *run_id* left on a run it took over, still blocked.

    Maps each to its blocker and the run that keeps it. One whose blocker now
    ships here or has shipped is not listed: enrollment admits it instead.
    """
    from yoke_core.domain.deployment_run_composition_freeze import member_ids
    from yoke_core.domain.deployment_run_membership_removals import (
        parse_membership_removals,
    )
    from yoke_core.domain.schema_common import _column_exists

    if not _column_exists(conn, "deployment_runs", "superseded_by_run_id"):
        return {}
    rows = conn.execute(
        "SELECT id,membership_removals FROM deployment_runs "
        "WHERE superseded_by_run_id=%s ORDER BY id",
        (run_id,),
    ).fetchall()
    members = set(member_ids(conn, run_id))
    source = {
        int(entry["item_id"]): str(row[0])
        for row in rows
        for entry in parse_membership_removals(row[1], str(row[0]))
        if entry.get("reason") == BLOCKED_SET_ASIDE_REASON
        and int(entry["item_id"]) not in members
    }
    blocked = blocked_members(conn, source, shipping=members)
    return {item_id: (blocker, source[item_id]) for item_id, blocker in blocked.items()}


def describe_blocked(conn: Any, blocked: dict[int, int]) -> str:
    """``YOK-2 (blocked by YOK-1); ...`` for a notice or receipt."""
    ref = render_item_ref_lookup(conn, [i for pair in blocked.items() for i in pair])
    return "; ".join(
        f"{ref(dependent)} (blocked by {ref(blocker)})"
        for dependent, blocker in sorted(blocked.items())
    )


__all__ = [
    "BLOCKED_SET_ASIDE_REASON",
    "blocked_members",
    "dependents_stranded_by",
    "describe_blocked",
    "left_by_takeover",
    "set_aside_blocked_members",
    "takeover_shipping",
]
