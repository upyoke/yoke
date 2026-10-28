"""Plan attachments and case-to-requirement snapshot materialization."""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.timestamps import utc_now
from yoke_core.domain.db_helpers import instant_parameter, query_one, query_rows
from yoke_core.domain.qa_plan_management import QaPlanError, _placeholder, _plan_row
from yoke_core.domain.qa_plan_case_definition import case_baselines, plan_cases
from yoke_core.domain.qa_plan_requirement_snapshot import (
    existing_requirement_id,
    insert_requirement,
)
from yoke_core.domain.qa_plan_attachment_reads import live_item_attachment_sql
from yoke_core.domain.qa_plan_attachment_validation import (
    refuse_unreachable_plan_attachment,
    require_plan_cases,
    validate_attached_item_transition,
    validate_item_transition,
)
from yoke_core.domain.schema_common import _column_exists
from yoke_core.domain.qa_deployment_plan_materialization import (
    materialize_deployment_plan,
)
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
    rollback_workflow_binding_write_errors,
)
from yoke_core.domain.qa_plan_case_targets import case_variants
from yoke_core.domain.qa_plan_project_defaults import (
    set_project_default,
    unset_project_default,
)
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime
from yoke_contracts.public_ref import ITEM_NOT_FOUND


PROJECT_DEFAULT_QA_POLICIES = frozenset(
    {"project_transition_defaults", "project_and_task_attachments"}
)


def workflow_uses_project_testing_defaults(conn: Any, item_id: int) -> bool:
    workflow = load_item_workflow_runtime(conn, int(item_id))
    return str(workflow.policies.get("qa") or "") in PROJECT_DEFAULT_QA_POLICIES


def attach_plan_to_item(
    conn: Any,
    *,
    plan_id: int,
    item_id: int,
    transition_id: str,
    qa_phase: str = "verification",
    actor_id: Optional[int] = None,
    commit: bool = True,
    acknowledge_unreachable_target: bool = False,
) -> dict:
    """Add an item-specific plan attachment after enforcing project scope."""
    plan = _plan_row(conn, plan_id)
    require_plan_cases(conn, plan_id)
    marker = _placeholder(conn)
    item = query_one(
        conn,
        f"SELECT project_id FROM items WHERE id={marker}",
        (int(item_id),),
    )
    if item is None:
        raise QaPlanError(ITEM_NOT_FOUND)
    if int(item["project_id"]) != int(plan["project_id"]):
        raise QaPlanError("plan and item must belong to the same project")
    lock_item_workflow_bindings(conn, (int(item_id),))
    transition_id = validate_item_transition(
        conn,
        item_id=int(item_id),
        transition_id=transition_id,
        plan_id=int(plan_id),
        qa_phase=qa_phase,
    )
    refuse_unreachable_plan_attachment(
        conn,
        item_id=int(item_id),
        plan=plan,
        transition_id=transition_id,
        qa_phase=qa_phase,
        acknowledge=acknowledge_unreachable_target,
    )
    now = utc_now()
    if _column_exists(conn, "qa_plan_item_attachments", "retracted_at"):
        existing = query_one(
            conn,
            "SELECT retracted_at FROM qa_plan_item_attachments "
            f"WHERE item_id={marker} AND transition_id={marker} "
            f"AND plan_id={marker}",
            (item_id, transition_id, plan_id),
        )
        if existing is not None and existing.get("retracted_at"):
            raise QaPlanError(
                f"plan {plan_id} was retracted for this item at {transition_id}; "
                "attach a different plan or record that no post-deploy obligation exists"
            )
    try:
        conn.execute(
            "INSERT INTO qa_plan_item_attachments("
            "item_id, transition_id, qa_phase, plan_id, attached_at, "
            "attached_by_actor_id"
            f") VALUES ({', '.join([marker] * 6)}) "
            "ON CONFLICT(item_id, transition_id, plan_id) DO UPDATE SET "
            "qa_phase=EXCLUDED.qa_phase, attached_at=EXCLUDED.attached_at, "
            "attached_by_actor_id=EXCLUDED.attached_by_actor_id",
            (
                item_id,
                transition_id,
                qa_phase,
                plan_id,
                instant_parameter(conn, now),
                actor_id,
            ),
        )
        if qa_phase == "post_deploy":
            # The plan's group is real post-deploy work for this item.
            from yoke_core.domain.qa_post_deploy_no_obligation_retirement import (
                retract_no_obligation_for_requirement,
            )

            retract_no_obligation_for_requirement(
                conn, item_id=int(item_id), requirement={"qa_phase": "post_deploy"}
            )
        if commit:
            conn.commit()
    except Exception:
        if commit:
            conn.rollback()
        raise
    return {
        "plan_id": int(plan_id),
        "item_id": int(item_id),
        "transition_id": transition_id,
        "qa_phase": qa_phase,
    }


def _attached_plans(
    conn: Any,
    *,
    item_id: int,
    transition_id: str,
) -> dict[int, dict]:
    marker = _placeholder(conn)
    item = query_one(
        conn,
        f"SELECT project_id, workflow_id FROM items WHERE id={marker}",
        (item_id,),
    )
    if item is None:
        raise QaPlanError(ITEM_NOT_FOUND)
    attachments: dict[int, dict] = {}
    if workflow_uses_project_testing_defaults(conn, int(item_id)):
        for row in query_rows(
            conn,
            "SELECT plan_id, qa_phase FROM qa_plan_project_defaults "
            f"WHERE project_id={marker} AND workflow_id={marker} "
            f"AND transition_id={marker} ORDER BY plan_id",
            (int(item["project_id"]), str(item["workflow_id"]), transition_id),
        ):
            attachments[int(row["plan_id"])] = dict(row)
    for row in query_rows(
        conn,
        "SELECT plan_id, qa_phase FROM qa_plan_item_attachments "
        f"WHERE item_id={marker} AND transition_id={marker} "
        f"AND {live_item_attachment_sql(conn)} ORDER BY plan_id",
        (item_id, transition_id),
    ):
        attachments[int(row["plan_id"])] = dict(row)
    return dict(sorted(attachments.items()))


def _owed_attachments(conn: Any, item_id: int, transition_id: str) -> dict[int, dict]:
    """This transition's item-bound attachments.

    A post-deploy plan is never copied onto its item: each release runs it
    once as a plan group (:mod:`deployment_qa_plan_group_writes`).
    """
    return {
        plan_id: attachment
        for plan_id, attachment in _attached_plans(
            conn, item_id=int(item_id), transition_id=str(transition_id)
        ).items()
        if attachment.get("qa_phase") != "post_deploy"
    }


def has_attached_plans(
    conn: Any,
    *,
    item_id: int,
    transition_id: str,
) -> bool:
    """Whether materialization has any effective work for this transition."""
    return bool(_owed_attachments(conn, item_id, transition_id))


@rollback_workflow_binding_write_errors
def materialize_for_item(
    conn: Any,
    *,
    item_id: int,
    transition_id: str,
    commit: bool = True,
    replacement_scopes: dict | None = None,
) -> dict:
    """Snapshot each attached plan once for this item and transition."""
    lock_item_workflow_bindings(conn, (int(item_id),))
    transition_id = str(transition_id or "").strip()
    attachments = _owed_attachments(conn, item_id, transition_id)
    if not attachments:
        # Nothing live to snapshot; post-deploy plans run as plan groups.
        # Do not re-ask a verification gate for an empty bind.
        return _materialized(int(item_id), transition_id, {}, [], [])
    transition_id = validate_attached_item_transition(
        conn,
        item_id=int(item_id),
        transition_id=transition_id,
        attachments=attachments,
    )
    marker = _placeholder(conn)
    created: list[int] = []
    existing: list[int] = []
    now = utc_now()
    snapshots: list[tuple[Any, dict, list[tuple[Any, str | None, dict]]]] = []
    for plan_id, attachment in attachments.items():
        rows = query_rows(
            conn,
            "SELECT id FROM qa_requirements "
            f"WHERE item_id={marker} AND plan_id={marker} "
            f"AND workflow_transition_id={marker} AND deployment_run_id IS NULL ORDER BY id",
            (item_id, plan_id, transition_id),
        )
        if rows:
            existing.extend(int(row["id"]) for row in rows)
            continue
        cases = plan_cases(conn, plan_id)
        if not cases:
            raise QaPlanError(
                f"QA plan {plan_id} has no cases and cannot be materialized"
            )
        plan = _plan_row(conn, plan_id)
        snapshots.append((plan, attachment, case_variants(conn, plan=plan, cases=cases)))

    for plan, attachment, variants in snapshots:
        for case, target_env, execution_target in variants:
            for baseline_position, baseline in enumerate(case_baselines(case), start=1):
                requirement_id = insert_requirement(
                    conn,
                    item_id=item_id,
                    transition_id=transition_id,
                    plan=plan,
                    attachment=attachment,
                    case=case,
                    baseline=baseline,
                    baseline_position=baseline_position,
                    now=now,
                    execution_target=execution_target,
                    target_env=target_env,
                )
                if requirement_id is None:
                    raise QaPlanError(
                        "qa_plan_snapshot_insert_conflict: initial snapshot conflicted "
                        "with an existing requirement. Inspect `yoke qa requirement "
                        "list --item <item>` and retry materialization."
                    )
                created.append(requirement_id)
    if replacement_scopes:
        from yoke_core.domain.qa_requirement_correction_selection import (
            validate_item_correction_selection,
        )

        validate_item_correction_selection(
            conn, item_id=item_id, transition_id=transition_id,
            attachments=attachments, scopes=replacement_scopes,
            requirement_ids=[*created, *existing],
        )
    if commit:
        conn.commit()
    return _materialized(int(item_id), transition_id, attachments, created, existing)


def _materialized(
    item_id: int,
    transition_id: str,
    attachments: dict[int, dict],
    created: list[int],
    existing: list[int],
) -> dict:
    return {
        "item_id": int(item_id),
        "transition_id": transition_id,
        "plan_ids": list(attachments),
        "created_requirement_ids": created,
        "existing_requirement_ids": existing,
    }


def materialize_for_deployment_run(
    conn: Any,
    *,
    deployment_run_id: str,
    plan: str,
    project: Optional[str] = None,
    commit: bool = True,
) -> dict:
    """Snapshot one named project plan onto a real deployment run."""
    return materialize_deployment_plan(
        conn,
        deployment_run_id=deployment_run_id,
        plan=plan,
        project=project,
        commit=commit,
        insert_requirement_fn=insert_requirement,
        existing_requirement_id_fn=existing_requirement_id,
    )


__all__ = [
    "attach_plan_to_item",
    "has_attached_plans",
    "materialize_for_deployment_run",
    "materialize_for_item",
    "PROJECT_DEFAULT_QA_POLICIES",
    "set_project_default",
    "unset_project_default",
    "workflow_uses_project_testing_defaults",
]
