"""Select complete frozen admissions without entering materialization writers."""

import json

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.deployment_qa_shared_plans import shared_subject
from yoke_core.domain.deployment_qa_snapshot_selection import require_complete_snapshot
from yoke_core.domain.deployment_run_project_sources import run_delivered_sha
from yoke_core.domain.qa_obligation_settlement import unretracted_requirement_sql
from yoke_core.domain.qa_execution_environment_target import target_digest
from yoke_core.domain.qa_plan_case_definition import snapshot_fan_out
from yoke_core.domain.qa_plan_case_targets import case_applies_to_target
from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_core.domain.qa_plan_requirement_snapshot import require_existing_target


def _incomplete(plan_id):
    raise QaPlanError(
        f"qa_admitted_plan_incomplete: plan {plan_id} has no complete canonical "
        "admission for this run, stage, member and target. Preserve the run and "
        "inspect `yoke qa requirement list --deployment-run-id RUN`; ask the "
        "control-plane operator to restore its original admission evidence."
    )


def admitted_plan_selection(conn, subject, target, projection, selector):
    """Return an ordinary receipt only for this subject's exact frozen plan."""
    project_id = int(subject.get("member_project_id") or subject["project_id"])
    plans = query_rows(
        conn,
        "SELECT id FROM qa_plans WHERE project_id=%s "
        "AND (slug=%s OR CAST(id AS TEXT)=%s) AND retired_at IS NULL",
        (project_id, str(selector), str(selector)),
    )
    if len(plans) != 1:
        raise QaPlanError(
            "qa_plan_selection_unavailable: select one active plan ID or slug "
            "in the requesting subject's project; inspect `yoke qa plan list`."
        )
    plan_id = int(plans[0]["id"])
    snapshots = [
        value
        for value in subject["flow_snapshot"].get("selections", [])
        if value.get("stage") == subject["stage"]["name"]
    ] + list((subject.get("member_snapshot") or {}).get("plans", []))
    if subject.get("shared_snapshot"):
        snapshots = [subject["shared_snapshot"]]
    snapshots = [s for s in snapshots if int(s["plan"]["id"]) == plan_id]
    if not snapshots and subject.get("member_item_id") is not None:
        # A shared group freezes its contract on the materializing member;
        # another attaching member need not carry a private snapshot copy.
        for member in projection.members():
            raw = member["requirement_snapshot"]
            frozen = raw if isinstance(raw, dict) else json.loads(str(raw or "{}"))
            for value in frozen.get("plans", []):
                if int(value["plan"]["id"]) == plan_id and projection.shareable(
                    subject, target, [value]
                ):
                    snapshots.append(value)
    if not snapshots:
        return None
    snapshot = snapshots[-1]
    require_complete_snapshot(snapshot)
    if subject.get("member_item_id") is not None:
        from yoke_core.domain.qa_plan_attachment_reads import retracted_item_plan_ids

        if plan_id in retracted_item_plan_ids(conn, int(subject["member_item_id"])):
            _incomplete(plan_id)
    cases = [c for c in snapshot["cases"] if case_applies_to_target(c, target)]
    snapshot = {**snapshot, "cases": cases}
    group = subject
    if projection.shareable(subject, target, [snapshot]):
        group = shared_subject(subject, target, snapshot)
    selected_target = deployment_qa_execution_target(conn, group)
    rows = query_rows(
        conn,
        "SELECT id,plan_case_key,host_baseline,method_id,execution_target_json,"
        "execution_target_digest FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_stage=%s AND COALESCE(deployment_member_item_id,0)=%s "
        "AND plan_id=%s AND execution_target_digest=%s "
        f"AND {unretracted_requirement_sql(conn)} "
        "ORDER BY case_position,baseline_position,id",
        (
            subject["id"],
            subject["stage"]["name"],
            group.get("member_item_id") or 0,
            plan_id,
            target_digest(selected_target),
        ),
    )
    if not rows:
        _incomplete(plan_id)
    fan_out = snapshot_fan_out(snapshot["plan"], cases)
    expected = {
        (key, baseline) for key, baselines in fan_out.items() for baseline in baselines
    }
    actual = [
        (r["plan_case_key"], r["host_baseline"]) for r in rows if r.get("method_id")
    ]
    if not expected or len(actual) != len(expected) or set(actual) != expected:
        _incomplete(plan_id)
    ids = require_existing_target(
        rows,
        execution_target=selected_target,
        subject=f"deployment run {subject['id']!r} stage {subject['stage']['name']!r}",
        conn=conn,
    )
    return {
        "deployment_run_id": str(subject["id"]),
        "deployment_stage": str(subject["stage"]["name"]),
        "deployment_member_item_id": subject.get("member_item_id"),
        "candidate_revision": run_delivered_sha(conn, str(subject["id"]), project_id),
        "execution_target": selected_target,
        "created_requirement_ids": [],
        "existing_requirement_ids": ids,
        "declared_no_post_deploy_verification": [],
        "no_item_qa_obligation": [],
    }
