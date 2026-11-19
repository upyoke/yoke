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
    "set_aside_blocked_members",
]
