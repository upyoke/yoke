"""Members a run delivered whose remaining QA belongs to another environment.

A run settles on its own target. Its final members' obligations targeted at
the run's environment must pass; an obligation targeted at another
environment — stage QA owed beside a production delivery — is answered by a
run on that environment, which this run can never admit. Such a member is
delivered here and stays open at its release wait: the run's success is its
delivery receipt and stamps ``deployed_to``, and the member closes against
that delivery once its remaining target's obligations pass.

A member still red on this run's own target, or owing anything that is not
an other-target post-deploy obligation, is not deferred and still blocks.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.deployment_member_post_deploy_admission import (
    outstanding_post_deploy_requirements,
)
from yoke_core.domain.deployment_qa_source_obligation import (
    latest_completion_run,
    unsatisfied_blocking,
)
from yoke_core.domain.deployment_run_member_targeting import (
    member_selected_requirement_ids,
    run_environment_name,
)


def owes_only_other_targets(conn: Any, *, run_id: str, item_id: int) -> bool:
    """Whether this run answered the member and only other targets remain.

    Every open done blocker must be post-deploy intake: either targeted at
    another environment, or one this run selected and answered (its source
    row reads open until the delivery itself is recorded). At least one must
    target another environment, or there is nothing to defer.
    """
    from yoke_core.domain.no_obligation_member_close_out import (
        satisfied_delivery_member,
    )

    environment = run_environment_name(conn, run_id)
    if not environment:
        return False
    if not satisfied_delivery_member(conn, item_id=int(item_id), run_id=str(run_id)):
        return False
    targets = {
        int(row["id"]): row["target_env"]
        for row in outstanding_post_deploy_requirements(conn, int(item_id))
    }
    selected = member_selected_requirement_ids(
        conn, run_id=str(run_id), item_id=int(item_id)
    )
    deferred = False
    blockers = unsatisfied_blocking(conn, item_id=int(item_id), target_status="done")
    for row in blockers.rows:
        requirement_id = int(row["id"])
        if requirement_id not in targets:
            return False
        target = targets[requirement_id]
        if target and target != environment:
            deferred = True
        elif requirement_id not in selected:
            return False
    return deferred


def split_other_target_members(
    conn: Any, run_id: str, members: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split members into those the run must close and those it defers."""
    required: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for member in members:
        owes = owes_only_other_targets(
            conn, run_id=run_id, item_id=int(member["item_id"])
        )
        (deferred if owes else required).append(member)
    return required, deferred


def record_other_target_deliveries(
    conn: Any, run_id: str, members: list[dict[str, Any]]
) -> None:
    """Stamp ``deployed_to`` on deferred members, inside the caller's commit."""
    from yoke_core.domain.backlog_item_db_writes import _update_item_multi

    environment = run_environment_name(conn, run_id)
    for member in members:
        _update_item_multi(
            conn, int(member["item_id"]), {"deployed_to": environment}, commit=False
        )


def close_after_other_target_acceptance(
    conn: Any, *, item_id: int, public_ref: str, run_id: str
) -> Any:
    """Close a member against its delivery once another target accepted it.

    ``run_id`` is the run whose QA was just accepted. When it is not the
    item's completion run, the close-out runs against the completion run if
    that run already succeeded or has independently delivered this member.
    Returns the close-out result, or ``None`` when this is not that case.
    """
    from yoke_core.domain.deployment_member_independent_close_out import (
        independent_member_delivery_ready,
    )
    from yoke_core.domain.no_obligation_member_close_out import (
        close_out_satisfied_delivery_member,
    )

    completion = latest_completion_run(conn, int(item_id))
    if completion is None or str(completion["id"]) == str(run_id):
        return None
    completion_id = str(completion["id"])
    if completion["status"] != "succeeded" and not independent_member_delivery_ready(
        conn, item_id=int(item_id), run_id=completion_id
    ):
        return None
    return close_out_satisfied_delivery_member(
        conn, item_id=int(item_id), public_ref=public_ref, run_id=completion_id
    )


__all__ = [
    "close_after_other_target_acceptance",
    "owes_only_other_targets",
    "record_other_target_deliveries",
    "split_other_target_members",
]
