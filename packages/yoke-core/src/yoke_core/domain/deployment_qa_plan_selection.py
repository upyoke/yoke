"""Select candidate-proven plans and scoped correction cases for deployment QA."""

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.deployment_qa_frozen_plan_selection import frozen_stage_plans
from yoke_core.domain.deployment_requirement_snapshots import _plan_snapshot
from yoke_core.domain.deployment_qa_stage_named_cases import (
    AGENT_PLAN_ALREADY_NAMED_REFUSAL,
    require_correction_only_plan,
    stage_names_cases,
)
from yoke_core.domain.post_deploy_verification_answer import cases_not_selected_refusal
from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_core.domain.qa_plan_source_revision import require_candidate_plan
from yoke_core.domain.deployment_qa_presentation_reads import presentation_read


def selected_plans(
    conn: Any,
    subject: Mapping[str, Any],
    *,
    agent_plan: str | None,
    target: Mapping[str, Any],
    admitted: list[dict[str, Any]],
    allow_empty: bool = False,
    lock_plans: bool = True,
    replacement_keys: set[str] | None = None,
    replacement_scopes: dict[str, list[dict]] | None = None,
) -> list[dict[str, Any]]:
    from yoke_core.domain.deployment_qa_stage_materialization import (
        QaCasesNotSelectedError,
    )

    frozen = frozen_stage_plans(
        conn, subject, target=target, admitted=admitted, lock_plans=lock_plans
    )
    named = agent_plan is not None and stage_names_cases(
        conn, subject, frozen_plans=frozen, admitted=admitted
    )
    if named and not replacement_keys:
        raise QaPlanError(AGENT_PLAN_ALREADY_NAMED_REFUSAL)
    if agent_plan is not None:
        plan_project_id = int(subject.get("member_project_id") or subject["project_id"])
        row = conn.execute(
            "SELECT id FROM qa_plans WHERE project_id=%s "
            "AND (slug=%s OR CAST(id AS TEXT)=%s) AND retired_at IS NULL",
            (plan_project_id, str(agent_plan), str(agent_plan)),
        ).fetchone()
        if row is None:
            raise QaPlanError(
                f"agent-selected QA plan {agent_plan!r} is not active in this project"
            )
        agent_plan_id = int(row["id"] if hasattr(row, "keys") else row[0])
        snapshot = _plan_snapshot(
            conn, int(agent_plan_id), project_id=plan_project_id, lock_plan=lock_plans
        )
        if named:
            require_correction_only_plan(snapshot, replacement_keys or set())
        if replacement_scopes:
            snapshot["replacement_scopes"] = replacement_scopes
        snapshot["selected_by_agent"] = True
        frozen = [
            value
            for value in frozen
            if not (
                value.get("selected_by_agent")
                and int(value["plan"]["id"]) == agent_plan_id
            )
        ]
        frozen.append(snapshot)
    unique: dict[tuple[int, tuple[str, ...]], dict[str, Any]] = {}
    for snapshot in frozen:
        plan = snapshot.get("plan")
        cases = snapshot.get("cases")
        if not isinstance(plan, Mapping) or not isinstance(cases, list):
            raise QaPlanError("frozen deployment QA plan snapshot is invalid")
        key = (
            int(plan["id"]),
            tuple(str(case["case_key"]) for case in cases if isinstance(case, Mapping)),
        )
        unique[key] = snapshot
    if not unique and not allow_empty:
        raise QaCasesNotSelectedError(cases_not_selected_refusal())
    from yoke_core.domain.qa_plan_case_targets import case_applies_to_target

    for snapshot in unique.values():
        plan = snapshot["plan"]
        presentation_read(
            conn,
            (
                "qa_candidate_plan",
                str(subject["id"]),
                int(plan["id"]),
                plan.get("source_revision"),
                int(plan["project_id"]),
            ),
            lambda: require_candidate_plan(conn, plan, str(subject["id"])),
        )
    return [
        {**snapshot, "cases": cases}
        for snapshot in unique.values()
        if (
            cases := [
                case
                for case in snapshot["cases"]
                if case_applies_to_target(case, target)
            ]
        )
    ]
