"""Create item-qa plan groups and build the run-scoped subject each one gates as.

Nothing is written for a plan before item QA: no item copy, no admission
snapshot. When an item-scoped stage materializes, each owed plan with no open
group in the run gets one, built from the plan as the release pinned it. The
first group of a plan in a run pins the plan into the run's snapshot, so a
later group of the same plan in the same run runs the same cases and a plan
edited mid-release waits for the next release.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from yoke_core.domain.deployment_qa_plan_groups import (
    PINNED_PLANS,
    PlanGroup,
    attached_plans,
    covered_members,
    run_groups,
)


def group_subject(
    conn: Any, run_id: str, stage_name: str, group: PlanGroup, *, require_active: bool
) -> dict:
    """The run-scoped subject a group settles as; no member owns it."""
    from yoke_core.domain.deployment_qa_stage_contract import _run_stage
    from yoke_core.domain.deployment_qa_stage_prerequisites import (
        require_prior_stage_acceptance,
    )

    run = _run_stage(conn, str(run_id), str(stage_name), require_active=require_active)
    if str(run["stage"].get("scope") or "") != "item":
        raise ValueError(
            f"plan_group_stage_not_item_scoped: stage {stage_name!r} of run {run_id!r} "
            "runs run QA, not plan groups; run it with `yoke qa plan run "
            f"--deployment-run-id {run_id} --stage {stage_name}`"
        )
    if require_active:
        require_prior_stage_acceptance(
            conn, run_id=str(run_id), stages=run["stages"], start_stage=str(stage_name)
        )
    marker = dict(group.target["deployment"]["shared_plan"])
    return {
        **run,
        "member_item_id": None,
        "member_snapshot": None,
        "member_project_id": int((group.target.get("project") or {}).get("id") or 0),
        "shared_plan": marker,
        "shared_target": dict(group.target),
    }


def _pinned_snapshot(conn: Any, run_id: str, plan_id: int, project_id: int) -> dict:
    """The plan as this release runs it: pinned at the run's first group of it."""
    from yoke_core.domain.deployment_requirement_snapshots import (
        _canonical,
        _plan_snapshot,
    )
    from yoke_core.domain.qa_plan_source_revision import require_candidate_plan

    row = conn.execute(
        "SELECT requirement_snapshot FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()
    raw = row["requirement_snapshot"] if hasattr(row, "keys") else row[0]
    payload = json.loads(str(raw or "{}")) if not isinstance(raw, Mapping) else dict(raw)
    pinned = payload.setdefault(PINNED_PLANS, {})
    snapshot = pinned.get(str(plan_id))
    if snapshot is None:
        snapshot = _plan_snapshot(conn, int(plan_id), project_id=int(project_id))
        pinned[str(plan_id)] = {"plan": dict(snapshot["plan"]), "cases": snapshot["cases"]}
        conn.execute(
            "UPDATE deployment_runs SET requirement_snapshot=%s WHERE id=%s",
            (_canonical(payload), run_id),
        )
    require_candidate_plan(conn, snapshot["plan"], str(run_id))
    return {"plan": dict(snapshot["plan"]), "cases": list(snapshot["cases"])}


def _next_group_id(conn: Any, run_id: str) -> str:
    """Creating run id plus a sequence; never reused, even after a retraction."""
    taken = {group.group_id for group in run_groups(conn, run_id)}
    sequence = len(taken) + 1
    while f"{run_id}:{sequence}" in taken:
        sequence += 1
    return f"{run_id}:{sequence}"


def _group_target(target: Mapping, identity: Mapping) -> dict:
    normalized = deepcopy(dict(target))
    normalized["deployment"].pop("member_item_id", None)
    normalized["deployment"]["shared_plan"] = dict(identity)
    return normalized


def ensure_groups(conn: Any, run_id: str, stage_name: str) -> list[int]:
    """Give each owed plan without an open group one; answer created row ids.

    The caller holds the run lock. A plan is owed when a current member
    attaches it and no closed group of it in this run or a run it superseded
    already answered that member.
    """
    from yoke_core.domain.deployment_qa_execution_target import (
        deployment_qa_execution_target,
    )
    from yoke_core.domain.deployment_qa_stage_contract import (
        deployment_qa_stage_subject,
    )
    from yoke_core.domain.deployment_qa_subject_materialization import (
        materialize_subject,
    )
    from yoke_core.domain.qa_plan_case_targets import case_applies_to_target

    open_plans = {g.plan_id for g in run_groups(conn, run_id, stage_name) if g.open}
    created: list[int] = []
    for plan_id, members in attached_plans(conn, run_id).items():
        if plan_id in open_plans:
            continue
        covered = covered_members(conn, run_id, plan_id)
        owing = [member for member in members if member not in covered]
        if not owing:
            continue
        subject = deployment_qa_stage_subject(
            conn, run_id=run_id, stage_name=stage_name, member_item_id=owing[0]
        )
        target = deployment_qa_execution_target(conn, subject)
        snapshot = _pinned_snapshot(
            conn, run_id, plan_id, int(subject["member_project_id"])
        )
        cases = [c for c in snapshot["cases"] if case_applies_to_target(c, target)]
        if not cases:
            continue
        identity = {
            "plan_id": int(plan_id),
            "source_revision": snapshot["plan"].get("source_revision"),
            "group_id": _next_group_id(conn, run_id),
        }
        group_target = _group_target(target, identity)
        group = {
            **subject,
            "member_item_id": None,
            "member_snapshot": None,
            "shared_plan": identity,
            "shared_target": group_target,
        }
        result = materialize_subject(
            conn,
            subject=group,
            target=group_target,
            admitted=[],
            snapshots=[{**snapshot, "cases": cases}],
            commit=False,
        )
        created.extend(result["created_requirement_ids"])
    return created


def _creating_run(group_id: str) -> str:
    return str(group_id).rsplit(":", 1)[0]


def resolve_group_subject(
    conn: Any, run_id: str, stage_name: str, plan: str, *, require_active: bool
) -> dict | None:
    """The open group of ``plan`` (slug or id) at an item stage; None at a run stage.

    A plan whose groups in this run all closed is owed nothing more here: the
    refusal names those groups so the caller reads them instead of guessing.
    """
    from yoke_core.domain.deployment_qa_stage_contract import _run_stage

    stage = _run_stage(conn, str(run_id), str(stage_name), require_active=False)["stage"]
    if str(stage.get("scope") or "") != "item":
        return None
    groups = [
        group
        for group in run_groups(conn, run_id, stage_name)
        if str(plan) in {str(group.plan_id), _plan_slug(conn, group.plan_id)}
    ]
    live = [group for group in groups if group.open]
    if live:
        return group_subject(conn, run_id, stage_name, live[0], require_active=require_active)
    closed = [group.group_id for group in groups if group.closed]
    raise ValueError(
        f"plan_group_not_open: plan {plan!r} has no open plan group in run {run_id!r} "
        f"stage {stage_name!r}"
        + (f"; closed groups {closed} already answered their items, so nothing is owed" if closed else "")
        + f". Read `yoke deployment-runs get {run_id}`: a plan group forms when the "
        "stage dispatches for a member that attaches the plan."
    )


def _plan_slug(conn: Any, plan_id: int) -> str:
    row = conn.execute("SELECT slug FROM qa_plans WHERE id=%s", (int(plan_id),)).fetchone()
    return "" if row is None else str(row["slug"] if hasattr(row, "keys") else row[0])


def group_snapshots(
    conn: Any,
    subject: Mapping,
    target: Mapping,
    replacement_keys: set[str] | None,
    replacement_scopes: dict | None,
) -> list[dict]:
    """The pinned cases a group runs, or the corrected cases that replace failed ones."""
    from yoke_core.domain.qa_plan_case_targets import case_applies_to_target

    marker = subject["shared_plan"]
    plan_id = int(marker["plan_id"])
    project_id = int(subject["member_project_id"])
    if replacement_keys:
        from yoke_core.domain.deployment_requirement_snapshots import _plan_snapshot
        from yoke_core.domain.qa_plan_source_revision import require_candidate_plan

        snapshot = _plan_snapshot(conn, plan_id, project_id=project_id)
        require_candidate_plan(conn, snapshot["plan"], str(subject["id"]))
        snapshot["cases"] = [
            case for case in snapshot["cases"] if case["case_key"] in replacement_keys
        ]
        if replacement_scopes:
            snapshot["replacement_scopes"] = replacement_scopes
        snapshot["selected_by_agent"] = True
    else:
        snapshot = _pinned_snapshot(
            conn, _creating_run(marker["group_id"]), plan_id, project_id
        )
    cases = [c for c in snapshot["cases"] if case_applies_to_target(c, target)]
    return [{**snapshot, "cases": cases}] if cases else []


def group_blockers(conn: Any, run_id: str, stage_name: str) -> list[tuple[str, str, list[str]]]:
    """Each open group's label, acceptance state and blockers; read only.

    Stage readers wait on these like on a member: an open group keeps its
    stage, and every later stage, from completing.
    """
    from yoke_core.domain.deployment_qa_stage_acceptance import stage_acceptance

    found = []
    for group in run_groups(conn, run_id, stage_name):
        if not group.open:
            continue
        subject = group_subject(conn, run_id, stage_name, group, require_active=False)
        answer = stage_acceptance(
            conn,
            subject=subject,
            target=subject["shared_target"],
            acceptance_qa_kind="deployment_stage_acceptance",
        )
        if answer.accepted:
            continue
        label = f"plan group {group.group_id} ({_plan_slug(conn, group.plan_id) or group.plan_id})"
        found.append((label, answer.state, list(answer.blockers) or ["not run yet"]))
    return found


__all__ = [
    "ensure_groups",
    "group_blockers",
    "group_snapshots",
    "group_subject",
    "resolve_group_subject",
]
