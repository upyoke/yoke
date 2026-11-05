"""Select complete frozen admissions without entering materialization writers."""

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_requirement_lineage import rows_by_case
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.deployment_qa_snapshot_selection import require_complete_snapshot
from yoke_core.domain.deployment_run_project_sources import run_delivered_sha
from yoke_core.domain.qa_execution_environment_target import target_digest
from yoke_core.domain.qa_plan_case_definition import snapshot_fan_out
from yoke_core.domain.qa_plan_case_targets import case_applies_to_target
from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_core.domain.qa_plan_requirement_snapshot import require_existing_target


def _incomplete(plan_id, subject):
    raise QaPlanError(
        f"qa_admitted_plan_incomplete: plan {plan_id} has no complete canonical "
        "admission for this run, stage, member and target. Preserve the run and "
        f"inspect `yoke qa requirement list --deployment-run-id {subject['id']}`; ask the "
        "control-plane operator to restore its original admission evidence."
    )


def admitted_plan_selection(conn, subject, target, selector):
    """Return an ordinary receipt only for this stage's exact frozen flow plan."""
    from yoke_core.domain.deployment_qa_member_plan_admission import (
        selection_applies_to_member,
    )

    project_id = int(subject.get("member_project_id") or subject["project_id"])
    plans = query_rows(
        conn,
        "SELECT id FROM qa_plans WHERE project_id=%s "
        "AND (slug=%s OR CAST(id AS TEXT)=%s) AND retired_at IS NULL",
        (project_id, str(selector), str(selector)),
    )
    if len(plans) != 1:
        raise QaPlanError(
            "qa_plan_selection_unavailable: plan is not active in this project; "
            "select one active plan ID or slug "
            f"in the requesting subject's project; inspect `yoke qa plan list --project {project_id}`."
        )
    plan_id = int(plans[0]["id"])
    snapshots = [
        value
        for value in subject["flow_snapshot"].get("selections", [])
        if value.get("stage") == subject["stage"]["name"]
        and int(value["plan"]["id"]) == plan_id
        and selection_applies_to_member(value, subject.get("member_item_id"))
    ]
    if not snapshots:
        return None
    snapshot = snapshots[-1]
    require_complete_snapshot(snapshot)
    cases = [c for c in snapshot["cases"] if case_applies_to_target(c, target)]
    snapshot = {**snapshot, "cases": cases}
    selected_target = deployment_qa_execution_target(conn, subject)
    groups = rows_by_case(
        conn,
        run_id=subject["id"],
        stage_name=subject["stage"]["name"],
        member_item_id=subject.get("member_item_id"),
        plan_id=plan_id,
    )
    if not groups:
        return None
    fan_out = snapshot_fan_out(snapshot["plan"], cases)
    selected_rows = []
    for case in cases:
        key = str(case["case_key"])
        scopes = snapshot.get("replacement_scopes", {}).get(key)
        for baseline in fan_out[key]:
            if scopes and not any(
                scope["host_baseline"] == baseline for scope in scopes
            ):
                continue
            canonical = groups.get((key, baseline), [])
            if not canonical:
                return None
            if any(
                row["execution_target_digest"] != target_digest(selected_target)
                for row in canonical
            ):
                return None  # Ordinary materialization rebinds the live heads.
            selected_rows.extend(canonical)
    if not selected_rows:
        _incomplete(plan_id, subject)
    rows = selected_rows
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
