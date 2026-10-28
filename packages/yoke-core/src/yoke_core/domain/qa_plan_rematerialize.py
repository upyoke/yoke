"""Refresh QA plan requirements while retaining completed run history.

This is the one supported way to bring a live item requirement back to its
plan's current text, and it reaches every executable column — instructions and
expected_outcome included — because :func:`refresh_requirement` rewrites the
derivation whole rather than going through the narrow ``qa.requirement.update``
allowlist. A case a live walk already reached refuses with the abort that
reopens the walk (:func:`carry_into_live_rosters`); a case it has not reached
takes the correction.

One call converges the transition on its item-bound plans: a case added since
the last materialization gets its row, an amended case's row is refreshed, and
a row whose case left the plan is waived as removed. A post-deploy plan is
never on its item: each release runs it once as a plan group pinned at the
release's plan revision, so an edited plan runs on the next release.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import instant_parameter, query_one, utc_now, query_rows
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_plan_case_targets import case_variants
from yoke_core.domain.qa_plan_attachment_validation import (
    validate_attached_item_transition,
)
from yoke_core.domain.qa_plan_attachments import _attached_plans
from yoke_core.domain.qa_plan_execution_roster_correction import (
    carry_into_live_rosters,
)
from yoke_core.domain.qa_plan_execution_target_snapshot import (
    rebind_unresolvable_targets,
)
from yoke_core.domain.qa_plan_case_definition import case_baselines, plan_cases
from yoke_core.domain.qa_obligation_settlement import obligation_settled
from yoke_core.domain.qa_plan_management import QaPlanError, _placeholder, _plan_row
from yoke_core.domain.qa_plan_requirement_snapshot import (
    existing_requirement_id,
    insert_requirement,
    refresh_requirement,
    require_existing_target,
    require_requirement_id_target,
)
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
    rollback_workflow_binding_write_errors,
)


REPLACEMENT_RATIONALE = "Removed from the current QA plan definition."

POST_DEPLOY_PLAN_GROUP_REFUSAL = (
    "post_deploy_plan_runs_as_plan_group: {subject} attaches only post-deploy "
    "plans {plan_ids}, which are never materialized on the item. Each release "
    "runs each one once as a plan group at item-qa, pinned at the plan revision "
    "the release started with; an edited plan runs on the next release. Run a "
    "plan group with `yoke qa plan run --deployment-run-id RUN --stage item-qa "
    "--plan P`."
)


@rollback_workflow_binding_write_errors
def rematerialize_for_item(
    conn: Any,
    *,
    item_id: int,
    transition_id: str,
    commit: bool = True,
) -> dict:
    """Refresh current plan snapshots and retire cases no longer in the plan."""
    lock_item_workflow_bindings(conn, (int(item_id),))
    transition_id = str(transition_id or "").strip()
    attached = _attached_plans(conn, item_id=int(item_id), transition_id=transition_id)
    attachments = {
        plan_id: attachment
        for plan_id, attachment in attached.items()
        if attachment.get("qa_phase") != "post_deploy"
    }
    if attached and not attachments:
        raise QaPlanError(
            POST_DEPLOY_PLAN_GROUP_REFUSAL.format(
                subject=f"{render_item_ref(conn, item_id)} transition {transition_id!r}",
                plan_ids=sorted(attached),
            )
        )
    if not attachments:
        return {
            "item_id": int(item_id),
            "transition_id": transition_id,
            "plan_ids": [],
            "created_requirement_ids": [],
            "refreshed_requirement_ids": [],
            "waived_requirement_ids": [],
        }
    transition_id = validate_attached_item_transition(
        conn,
        item_id=int(item_id),
        transition_id=transition_id,
        attachments=attachments,
    )
    marker = _placeholder(conn)
    # Post-deploy rows left on items by the old copy model are history only.
    rows = query_rows(
        conn,
        "SELECT * FROM qa_requirements "
        f"WHERE item_id={marker} AND workflow_transition_id={marker} "
        "AND plan_id IS NOT NULL AND deployment_run_id IS NULL "
        "AND COALESCE(qa_phase,'')<>'post_deploy' ORDER BY id",
        (int(item_id), transition_id),
    )
    subject = f"{render_item_ref(conn, item_id)} transition {transition_id!r}"
    rows_by_plan: dict[int, list[Any]] = {}
    for row in rows:
        rows_by_plan.setdefault(int(row["plan_id"]), []).append(row)
    created_requirement_ids: list[int] = []
    refreshed_requirement_ids: list[int] = []
    retained_requirement_ids: set[int] = set()
    now = utc_now()
    for plan_id, attachment in attachments.items():
        plan = _plan_row(conn, plan_id)
        cases = plan_cases(conn, plan_id)
        if not cases:
            raise QaPlanError(
                f"QA plan {plan_id} has no cases and cannot be materialized"
            )
        variants = case_variants(conn, plan=plan, cases=cases)
        for case, target_env, execution_target in variants:
            plan_rows = [
                row
                for row in rows_by_plan.get(plan_id, [])
                if (row["target_env"] or None) == target_env
                and row["plan_case_key"] == case["case_key"]
            ]
            plan_rows = rebind_unresolvable_targets(
                conn, plan_rows, execution_target=execution_target
            )
            require_existing_target(
                plan_rows, execution_target=execution_target, subject=subject, conn=conn
            )
            existing_ids = {
                (str(row["plan_case_key"]), row["host_baseline"]): int(row["id"])
                for row in plan_rows
            }
            for baseline_position, baseline in enumerate(case_baselines(case), start=1):
                key = (str(case["case_key"]), baseline)
                requirement_id = existing_ids.get(key)
                if requirement_id is None:
                    requirement_id = insert_requirement(
                        conn,
                        item_id=int(item_id),
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
                    if requirement_id is not None:
                        created_requirement_ids.append(requirement_id)
                    else:
                        requirement_id = existing_requirement_id(
                            conn,
                            item_id=int(item_id),
                            plan_id=plan_id,
                            case_key=key[0],
                            baseline=baseline,
                            transition_id=transition_id,
                            target_env=target_env,
                        )
                        if requirement_id is None:
                            raise QaPlanError("could not refresh QA plan requirement")
                        require_requirement_id_target(
                            conn,
                            requirement_id=requirement_id,
                            execution_target=execution_target,
                            subject=subject,
                        )
                else:
                    refresh_requirement(
                        conn,
                        requirement_id=requirement_id,
                        transition_id=transition_id,
                        plan=plan,
                        attachment=attachment,
                        case=case,
                        baseline=baseline,
                        baseline_position=baseline_position,
                        execution_target=execution_target,
                        target_env=target_env,
                    )
                    refreshed_requirement_ids.append(requirement_id)
                retained_requirement_ids.add(requirement_id)
    waived_requirement_ids = [
        int(row["id"])
        for row in rows
        if not obligation_settled(row)
        and int(row["id"]) not in retained_requirement_ids
    ]
    for requirement_id in waived_requirement_ids:
        conn.execute(
            "UPDATE qa_requirements "
            f"SET waived_at={marker}, waiver_rationale={marker}, "
            f"waiver_source={marker} WHERE id={marker}",
            (
                instant_parameter(conn, utc_now()),
                REPLACEMENT_RATIONALE,
                "system",
                requirement_id,
            ),
        )
    # A refusal here raises inside this transaction, so the rollback leaves
    # every row and roster as it was; a passed case is never replayed.
    carry_into_live_rosters(
        conn,
        subject=subject,
        rewritten=[*refreshed_requirement_ids, *waived_requirement_ids],
        created=created_requirement_ids,
        item_id=int(item_id),
        transition_id=transition_id,
    )
    if commit:
        conn.commit()
    return {
        "item_id": int(item_id),
        "transition_id": transition_id,
        "plan_ids": list(attachments),
        "created_requirement_ids": created_requirement_ids,
        "refreshed_requirement_ids": refreshed_requirement_ids,
        "waived_requirement_ids": waived_requirement_ids,
    }




#: Subject columns that decide which refresh invocation reaches a row.
_REFRESH_SUBJECT_SQL = (
    "SELECT id,execution_target_json,item_id,deployment_run_id,deployment_stage,"
    "deployment_member_item_id,plan_id,qa_phase,workflow_transition_id "
    "FROM qa_requirements WHERE id="
)


def _column(row: Any, key: str) -> Any:
    return row[key] if key in row.keys() else None


def refresh_invocation(conn: Any, row: Any) -> str:
    """The one refresh command that reaches this row, by its own subject.

    An item row and a deployment row are refreshed by different subjects of
    the same operation. A plan group runs its plan as the release pinned it,
    and a post-deploy row left on an item is history, so neither has one.
    """
    from yoke_core.domain.deployment_qa_plan_groups import group_marker

    if row["deployment_run_id"]:
        member = row["deployment_member_item_id"]
        if member is None and group_marker(_column(row, "execution_target_json")):
            return ""
        if (
            member is not None
            and query_one(
                conn,
                "SELECT 1 FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
                (row["deployment_run_id"], member),
            )
            is None
        ):
            return ""
        subject = (
            f"--item {render_item_ref(conn, int(member))}"
            if member
            else f"--deployment-run-id {row['deployment_run_id']}"
        )
        plan = f" --plan {row['plan_id']}" if row["plan_id"] is not None else ""
        return f"yoke qa plan rematerialize {subject} --stage {row['deployment_stage']}{plan}"
    if row["item_id"] and _column(row, "qa_phase") != "post_deploy":
        return (
            "yoke qa plan rematerialize --item "
            f"{render_item_ref(conn, int(row['item_id']))} "
            f"--transition {row['workflow_transition_id']}"
        )
    return ""


def refresh_recovery(conn: Any, row: Any) -> str:
    """The refresh sentence for a reader, or what to do when none reaches it."""
    invocation = refresh_invocation(conn, row)
    if invocation:
        return f"Refresh it from the plan with `{invocation}`."
    return (
        "No current refresh subject reaches this row (it may have lost its "
        "run membership, or it belongs to a plan group, which runs its plan as "
        "the release pinned it); inspect its subject with "
        "`yoke qa requirement list`, then supersede it with "
        "`yoke qa requirement supersede` "
        "or waive it through the registered waiver surface."
    )


def plan_refresh_invocation(conn: Any, requirement_id: int) -> str:
    """The refresh that reaches this row from its plan, or ``""`` if none does."""
    row = query_one(
        conn, f"{_REFRESH_SUBJECT_SQL}{_placeholder(conn)}", (int(requirement_id),)
    )
    if row is None or row["plan_id"] is None:
        return ""
    return refresh_invocation(conn, row)


__all__ = [
    "POST_DEPLOY_PLAN_GROUP_REFUSAL",
    "REPLACEMENT_RATIONALE",
    "plan_refresh_invocation",
    "refresh_invocation",
    "refresh_recovery",
    "rematerialize_for_item",
]
