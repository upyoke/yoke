"""Members a run delivered whose remaining QA belongs to another environment.

A run settles on its own target. Its final members' obligations targeted at
the run's environment must pass; an obligation targeted at another
environment — stage QA owed beside a production delivery — is answered by a
run on that environment, which this run can never admit. Such a member is
delivered here and stays open at its release wait: the run's success is its
delivery receipt and stamps ``deployed_to``, and the member closes against
that delivery once its remaining target's obligations pass. Setting a
member aside sends its holder (or the project's steering seat) one notice
naming each owed requirement, its environment and how to run it, because
nothing else drives that remaining acceptance.

A member still red on this run's own target, or owing anything that is not
an other-target post-deploy or manual-acceptance obligation, is not deferred and still blocks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from yoke_contracts.timestamps import parse_instant, utc_now
from yoke_core.domain.deployment_member_post_deploy_admission import (
    outstanding_post_deploy_requirements,
    requirement_target_environment,
)
from yoke_core.domain.deployment_qa_source_obligation import (
    latest_completion_run,
    unsatisfied_blocking,
)
from yoke_core.domain.deployment_run_member_targeting import (
    member_selected_requirement_ids,
    run_environment_name,
)

_LOG = logging.getLogger(__name__)

#: One set-aside notice per member and the run that delivered it.
SET_ASIDE_KEY_PREFIX = "other-target-set-aside:"


@dataclass(frozen=True)
class OwedRequirement:
    """One open done blocker and the environment it must pass on."""

    requirement_id: int
    phase: str
    target: str


def owed_requirements(conn: Any, item_id: int) -> tuple[OwedRequirement, ...]:
    """The item's open done blockers, each with its declared target."""
    blockers = unsatisfied_blocking(conn, item_id=int(item_id), target_status="done")
    return tuple(
        OwedRequirement(
            requirement_id=int(row["id"]),
            phase=str(row.get("qa_phase") or "undeclared"),
            target=requirement_target_environment(
                row.get("target_env"), row.get("execution_target_json")
            )
            or "",
        )
        for row in blockers.rows
    )


def owed_on_other_targets(
    conn: Any, item_id: int, environment: str
) -> tuple[OwedRequirement, ...]:
    """The open done blockers a delivery to ``environment`` cannot answer."""
    return tuple(
        entry
        for entry in owed_requirements(conn, item_id)
        if entry.target != environment
    )


def owes_only_other_targets(conn: Any, *, run_id: str, item_id: int) -> bool:
    """Whether this run answered the member and only other targets remain.

    Every open done blocker must be post-deploy intake or manual acceptance: targeted at
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
        target = targets.get(requirement_id)
        if row.get("qa_phase") == "manual_acceptance":
            target = requirement_target_environment(
                row.get("target_env"), row.get("execution_target_json")
            )
            if not target or target == environment:
                return False
        elif requirement_id not in targets:
            return False
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


def notify_set_aside_members(
    conn: Any, run_id: str, members: list[dict[str, Any]]
) -> None:
    """Tell each deferred member's owner what remains, after settlement commits.

    A failed send rolls back only its own message and is logged by name; the
    committed settlement stands and the fleet report still names what is owed.
    """
    environment = run_environment_name(conn, run_id)
    for member in members:
        _notify_set_aside(conn, run_id=run_id, environment=environment, member=member)


def set_aside_message(
    *,
    public_ref: str,
    run_id: str,
    environment: str,
    owed: tuple[OwedRequirement, ...],
    route: str,
) -> str:
    """Name each owed requirement, its environment, and how to run it."""
    from yoke_core.domain.merge_queue_landing_notice import HOLDER

    lines = [
        f"{public_ref} was delivered to {environment} by deployment run {run_id}, "
        "which succeeded without it closing. It stays open at its release wait "
        "until these requirements pass on their own environments:"
    ]
    for entry in owed:
        target = entry.target or "unspecified"
        lines.append(
            f"- requirement {entry.requirement_id} ({entry.phase}) on {target}: run it "
            f"on that environment's deployment run with `yoke qa plan run "
            f"--deployment-run-id RUN --stage STAGE --member {public_ref}`"
        )
    lines.append(
        f"Read `yoke qa requirement list --item {public_ref}` for each case and "
        "`yoke deployment-runs list` for the run on each environment. The item "
        "closes against this delivery once they pass; delivery never accepts or "
        "waives them."
    )
    if route == HOLDER:
        lines.append("You hold its work claim, so this acceptance is yours to drive.")
    else:
        lines.append("Nobody holds its work claim; staff this acceptance.")
    return "\n".join(lines)


def _notify_set_aside(
    conn: Any, *, run_id: str, environment: str, member: dict[str, Any]
) -> None:
    from yoke_core.domain.merge_queue_landing_notice import push_notice

    item_id = int(member["item_id"])
    owed = owed_on_other_targets(conn, item_id, environment)
    if not owed:
        return
    public_ref = str(member["public_ref"])
    try:
        delivery = push_notice(
            conn,
            item_id=item_id,
            project_id=int(member["project_id"]),
            body_for_route=lambda route: set_aside_message(
                public_ref=public_ref,
                run_id=str(run_id),
                environment=environment,
                owed=owed,
                route=route,
            ),
            idempotency_key=f"{SET_ASIDE_KEY_PREFIX}{item_id}:{run_id}",
            now=parse_instant(utc_now()),
        )
        conn.commit()
    except Exception:  # noqa: BLE001 - a failed notice never undoes settlement
        conn.rollback()
        _LOG.exception(
            "set-aside notice for %s on run %s failed; the fleet report still "
            "names its owed requirements",
            public_ref,
            run_id,
        )
        return
    if not delivery:
        _LOG.warning(
            "set-aside notice for %s on run %s found no holder or steering seat; "
            "the fleet report still names its owed requirements",
            public_ref,
            run_id,
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
    "OwedRequirement",
    "SET_ASIDE_KEY_PREFIX",
    "owed_on_other_targets",
    "owed_requirements",
    "notify_set_aside_members",
    "owes_only_other_targets",
    "record_other_target_deliveries",
    "set_aside_message",
    "split_other_target_members",
]


def member_completion_blocker(conn: Any, *, run_id: str, item_id: int) -> str:
    """Name the exact still-open acceptance facts without changing them."""
    from yoke_core.domain.project_identity import render_item_ref

    public_ref = render_item_ref(conn, item_id)
    details = [
        f"requirement {entry.requirement_id} phase {entry.phase} "
        f"target {entry.target or 'unspecified'}"
        for entry in owed_requirements(conn, item_id)
    ]
    if details:
        return (
            f"final member {public_ref} still owes "
            + "; ".join(details)
            + f"; read `yoke qa requirement list --item {public_ref}` and satisfy each named "
            "requirement on its declared target; delivery never accepts or waives it"
        )
    return (
        f"final member {public_ref} has not independently closed; read `yoke items get {public_ref} status` "
        f"and `yoke deployment-runs get {run_id}` and complete its pinned close-out"
    )
