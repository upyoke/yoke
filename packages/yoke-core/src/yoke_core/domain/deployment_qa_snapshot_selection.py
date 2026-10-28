"""Complete frozen plan contracts and the run selections that own them."""

import json
from collections.abc import Mapping

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.deployment_requirement_snapshot_format import (
    CASE_FIELDS,
    PLAN_FIELDS,
)
from yoke_core.domain.deployment_requirement_snapshots import _canonical
from yoke_core.domain.deployment_qa_source_plan_refresh import REFRESHED_CONTRACT
from yoke_core.domain.qa_plan_management import QaPlanError


def incomplete_snapshot(plan_id, detail):
    raise QaPlanError(
        f"qa_frozen_plan_snapshot_incomplete: plan {plan_id}: {detail}. "
        "Preserve the run and its requirement/results evidence. Ask the "
        "control-plane operator to prepare a reviewed repair from original "
        "admission evidence using operator.data_repair.run before resuming; "
        "current plan definitions cannot supply historical acceptance."
    )


def require_complete_snapshot(snapshot):
    """Refuse incomplete executable contracts without interpreting live cases."""
    plan = snapshot.get("plan")
    plan_id = plan.get("id") if isinstance(plan, Mapping) else "unknown"
    if not isinstance(plan, Mapping) or set(PLAN_FIELDS) - plan.keys():
        incomplete_snapshot(plan_id, "frozen plan fields are missing")
    cases = snapshot.get("cases")
    if not isinstance(cases, list) or not cases:
        incomplete_snapshot(plan_id, "frozen cases are missing")
    for case in cases:
        if not isinstance(case, Mapping) or set(CASE_FIELDS) - case.keys():
            incomplete_snapshot(plan_id, "frozen case fields are missing")
        if not case.get("config_contract_id"):
            incomplete_snapshot(plan_id, "frozen method config contract is missing")


def materialized_plan_ids(conn, subject):
    """Detect prior selection, without reconstructing a plan from requirements."""
    from yoke_core.domain.deployment_qa_presentation_facts import stage_requirement_rows
    from yoke_core.domain.deployment_qa_presentation_reads import presentation_read

    rows = stage_requirement_rows(conn, subject["id"], subject["stage"]["name"])
    if rows is None:
        rows = presentation_read(
            conn,
            ("qa_materialized_plan_ids", subject["id"], subject["stage"]["name"]),
            lambda: query_rows(
                conn,
                "SELECT plan_id,deployment_member_item_id FROM qa_requirements "
                "WHERE deployment_run_id=%s AND deployment_stage=%s "
                "AND plan_id IS NOT NULL AND method_id IS NOT NULL",
                (subject["id"], subject["stage"]["name"]),
            ),
        )
    member = subject.get("member_item_id")
    return {
        int(row["plan_id"])
        for row in rows
        if row["plan_id"] is not None and row["deployment_member_item_id"] == member
    }


def plan_matches_target(conn, plan, target, stage_environment_id):
    """Include the existing authorized hosted bridge without changing targets."""
    from yoke_core.domain.qa_deployment_member_attached_plans import (
        plan_matches_stage_environment,
    )
    from yoke_core.domain.qa_hosted_runtime_identity import (
        resolve_plan_environment_reference,
    )
    from yoke_core.domain.deployment_qa_presentation_reads import presentation_read

    if plan_matches_stage_environment(
        plan.get("target_environment_id"), stage_environment_id
    ):
        return True
    project_id = int(plan["project_id"])
    if project_id != int(target["project"]["id"]):
        return False
    name = str(target["environment"].get("name") or "")

    def bridge():
        try:
            row = resolve_plan_environment_reference(
                conn, plan_project_id=project_id, environment=name
            )
        except ValueError:
            return None
        return (
            row["environment_id"]
            if int(row["owner_project_id"]) != project_id
            else None
        )

    resolved = presentation_read(
        conn, ("qa_hosted_plan_environment", project_id, name), bridge
    )
    return resolved is not None and int(plan["target_environment_id"]) == int(resolved)


def freeze_selected_plans(conn, subject, snapshots):
    """Persist a run subject's new selections with their first cases.

    The caller holds the run lock. An existing contract changes here only to
    the saved source its stage refreshed it to before first materializing it;
    explicit rematerialization owns changes to a previously materialized plan.
    A member subject runs the run's flow selections and freezes nothing of its
    own; a plan group is pinned in ``plan_groups`` when it is created.
    """
    if (
        not snapshots
        or subject.get("shared_plan")
        or subject.get("member_item_id") is not None
    ):
        return
    row = conn.execute(
        "SELECT requirement_snapshot FROM deployment_runs WHERE id=%s",
        (subject["id"],),
    ).fetchone()
    payload = json.loads(str(row["requirement_snapshot"]))
    values = payload.setdefault("selections", [])
    stage = subject["stage"]["name"]
    existing = {
        int(value["plan"]["id"]): index
        for index, value in enumerate(values)
        if value.get("stage") == stage
    }
    changed = False
    for snapshot in snapshots:
        require_complete_snapshot(snapshot)
        plan_id = int(snapshot["plan"]["id"])
        index = existing.get(plan_id)
        refreshed = snapshot.get(REFRESHED_CONTRACT)
        if index is not None and not snapshot.get("selected_by_agent"):
            if refreshed is None:
                continue
            value = {**values[index], "plan": dict(refreshed["plan"])}
            value["cases"] = refreshed["cases"]
            if values[index] != value:
                values[index] = value
                changed = True
            continue
        value = {"plan": dict(snapshot["plan"]), "cases": snapshot["cases"]}
        for key in ("selected_by_agent", "replacement_scopes"):
            if key in snapshot:
                value[key] = snapshot[key]
        value["stage"] = stage
        if index is not None:
            if values[index] == value:
                continue
            values[index] = value
        else:
            existing[plan_id] = len(values)
            values.append(value)
        changed = True
    if changed:
        conn.execute(
            "UPDATE deployment_runs SET requirement_snapshot=%s WHERE id=%s",
            (_canonical(payload), subject["id"]),
        )
