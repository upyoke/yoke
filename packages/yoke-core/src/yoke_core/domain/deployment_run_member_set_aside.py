"""Set reworking members aside without cancelling their unfinished QA.

A member whose hard-block blocker is set aside would then wait on a blocker
this run no longer ships, so it is set aside with it, transitively
(:mod:`deployment_run_blocked_dependents`).
"""

from yoke_core.domain.deployment_landing_guard import reworking_members
from yoke_core.domain.deployment_run_blocked_dependents import (
    BLOCKED_SET_ASIDE_REASON,
    dependents_stranded_by,
    set_aside_blocked_members,
)
from yoke_core.domain.deployment_run_member_removal import remove_members_on
from yoke_core.domain.deployment_runs_lock import lock_run_with_stable_membership

SET_ASIDE_REASON = "member is reworking; awaiting enrollment in a later release"

#: Removals that keep the member's QA for the release that enrolls it next.
SET_ASIDE_REASONS = frozenset({SET_ASIDE_REASON, BLOCKED_SET_ASIDE_REASON})


def set_aside_reworking_members(conn, run_id, item_ids):
    candidates = reworking_members(conn, item_ids)
    if not candidates:
        return {}
    status, held = lock_run_with_stable_membership(conn, run_id)
    if status not in {"created", "executing", "failed"}:
        return {}
    current = reworking_members(conn, candidates.intersection(held), reconcile=False)
    removed = remove_members_on(
        conn, run_id, current, reason=SET_ASIDE_REASON,
        removed_by="reopened for rework", preserve_qa=True,
    )
    if current:
        stranded = dependents_stranded_by(conn, current, set(held) - current)
        removed.update(set_aside_blocked_members(conn, run_id, stranded))
    return removed
