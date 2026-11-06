"""Set reworking members aside without cancelling their unfinished QA."""

from yoke_core.domain.deployment_landing_guard import reworking_members
from yoke_core.domain.deployment_run_member_removal import remove_members_on
from yoke_core.domain.deployment_runs_lock import lock_run_with_stable_membership

SET_ASIDE_REASON = "member is reworking; awaiting enrollment in a later release"


def set_aside_reworking_members(conn, run_id, item_ids):
    candidates = reworking_members(conn, item_ids)
    if not candidates:
        return {}
    status, held = lock_run_with_stable_membership(conn, run_id)
    if status not in {"created", "executing", "failed"}:
        return {}
    current = reworking_members(conn, candidates.intersection(held), reconcile=False)
    return remove_members_on(
        conn, run_id, current, reason=SET_ASIDE_REASON,
        removed_by="reopened for rework", preserve_qa=True,
    )
