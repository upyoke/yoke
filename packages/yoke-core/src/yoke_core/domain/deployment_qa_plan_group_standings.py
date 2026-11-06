"""Acceptance standings for open shared plan groups and their members."""

from typing import Any

from yoke_core.domain.deployment_qa_plan_groups import covered_members
from yoke_core.domain.deployment_qa_plan_group_writes import group_subject, _plan_slugs


def _open_group_standings(conn: Any, run_id: str, stage_name: str) -> list[tuple]:
    from yoke_core.domain.deployment_qa_stage_acceptance import stage_acceptance

    from yoke_core.domain.deployment_qa_plan_groups import presented_stage_groups

    from yoke_core.domain.deployment_qa_plan_groups import attached_plans

    attached = attached_plans(conn, run_id)
    groups = [g for g in presented_stage_groups(conn, run_id, stage_name)
              if g.open and attached.get(g.plan_id)]
    slugs = _plan_slugs(conn, {group.plan_id for group in groups})
    found = []
    for group in groups:
        subject = group_subject(conn, run_id, stage_name, group, require_active=False)
        answer = stage_acceptance(
            conn,
            subject=subject,
            target=subject["shared_target"],
            acceptance_qa_kind="deployment_stage_acceptance",
        )
        if answer.accepted:
            continue
        label = (
            f"plan group {group.group_id} ({slugs.get(group.plan_id) or group.plan_id})"
        )
        command = f"yoke qa plan run --deployment-run-id {run_id} --stage {stage_name} --plan {group.plan_id}"
        from yoke_core.domain.deployment_qa_plan_group_failure import group_failed
        from yoke_core.domain.deployment_qa_failure_triage import pinned_source_guidance

        recovery = f"requirements {list(group.requirement_ids)}: `{command}`"
        if (
            answer.failed_requirement_ids
            or answer.state == "rejected"
            or group_failed(conn, group, {})
        ):
            recovery += " " + pinned_source_guidance(conn, run_id)
        found.append((group.plan_id, label, answer.state, [*answer.blockers, recovery]))
    return found


def group_blockers(
    conn: Any, run_id: str, stage_name: str
) -> list[tuple[str, str, list[str]]]:
    """Each open group's label, acceptance state and blockers; read only.

    Stage readers wait on these like on a member: an open group keeps its
    stage, and every later stage, from completing.
    """
    return [entry[1:] for entry in _open_group_standings(conn, run_id, stage_name)]


def member_group_blockers(
    conn: Any, run_id: str, stage_name: str, item_id: int
) -> list[tuple[str, str, list[str]]]:
    """The open groups still owed for plans this member attaches; read once per run."""
    from yoke_core.domain.deployment_qa_plan_groups import attached_plans
    from yoke_core.domain.deployment_qa_presentation_reads import presentation_read

    standings = presentation_read(
        conn,
        ("plan_group_standings", str(run_id), str(stage_name)),
        lambda: _open_group_standings(conn, str(run_id), str(stage_name)),
    )
    if not standings:
        return []
    plans = presentation_read(
        conn,
        ("plan_group_attachers", str(run_id)),
        lambda: attached_plans(conn, str(run_id)),
    )
    return [
        entry[1:]
        for entry in standings
        if int(item_id) in plans.get(entry[0], ())
        and int(item_id) not in covered_members(conn, run_id, entry[0])
    ]
