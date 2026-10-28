"""Immutable QA inputs captured when a deployment run starts."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_requirement_snapshot_format import (
    CASE_FIELDS,
    CASE_WAKE_FIELDS,
    PLAN_FIELDS,
    REQUIREMENT_FIELDS,
    semantic_row,
)
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.project_identity import render_item_ref


SNAPSHOT_SCHEMA = 1
SELECTION_SCHEMA = 1


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _positive_ids(values: Iterable[Any], *, field: str) -> list[int]:
    normalized: list[int] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} must contain positive integer ids")
        normalized.append(int(value))
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field} must not contain duplicate ids")
    return sorted(normalized)


def requirement_selection(*, requirement_ids: Iterable[int] = ()) -> str:
    """Encode an explicit per-member requirement selection.

    Post-deploy plans run as plan groups, so a selection names no plans: its
    ``plan_ids`` is always empty, and a stored one is ignored.
    """
    return _canonical(
        {
            "schema": SELECTION_SCHEMA,
            "requirement_ids": _positive_ids(requirement_ids, field="requirement_ids"),
            "plan_ids": [],
        }
    )


def _selection(raw: Any) -> dict[str, Any]:
    if raw in (None, ""):
        return {
            "schema": SELECTION_SCHEMA,
            "requirement_ids": [],
            "plan_ids": [],
        }
    try:
        decoded = json.loads(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError("member requirement_selection is not valid JSON") from exc
    if not isinstance(decoded, Mapping):
        raise ValueError("member requirement_selection must be a JSON object")
    if set(decoded) != {"schema", "requirement_ids", "plan_ids"}:
        raise ValueError(
            "member requirement_selection must contain only schema, "
            "requirement_ids and plan_ids"
        )
    if decoded.get("schema") != SELECTION_SCHEMA:
        raise ValueError(
            f"member requirement_selection schema must be {SELECTION_SCHEMA}"
        )
    return {
        "schema": SELECTION_SCHEMA,
        "requirement_ids": _positive_ids(
            decoded.get("requirement_ids") or [], field="requirement_ids"
        ),
        "plan_ids": [],
    }


def _plan_snapshot(
    conn: Any,
    plan_id: int,
    *,
    project_id: int,
    case_keys: Iterable[str] | None = None,
    lock_plan: bool = True,
) -> dict[str, Any]:
    from yoke_core.domain.deployment_qa_shared_plan_reads import (
        plan_snapshot_row,
        plan_snapshot_cases,
    )

    raw_plan = plan_snapshot_row(conn, plan_id, lock_plan=lock_plan)
    if raw_plan is None:
        raise LookupError(f"QA plan {plan_id} not found")
    plan = semantic_row(raw_plan, PLAN_FIELDS)
    if int(plan["project_id"]) != int(project_id):
        raise ValueError(f"QA plan {plan_id} belongs to another project")
    if raw_plan.get("retired_at") is not None:
        raise ValueError(f"QA plan {plan_id} is retired")
    requested = [str(value) for value in (case_keys or ())]
    if any(not value for value in requested) or len(requested) != len(set(requested)):
        raise ValueError(f"QA plan {plan_id} case_keys must be unique non-empty names")
    cases = [
        semantic_row(raw, (*CASE_FIELDS, *CASE_WAKE_FIELDS))
        for raw in plan_snapshot_cases(conn, plan_id, lock_plan=lock_plan)
    ]
    from yoke_contracts.qa_case_starting_state import (
        StartingStateError,
        chain_baselines,
        require_selected_chains,
    )

    try:
        chain_baselines(cases)
        if requested:
            by_key = {str(case["case_key"]): case for case in cases}
            missing = sorted(set(requested) - set(by_key))
            if missing:
                raise LookupError(f"QA plan {plan_id} has no cases: {missing}")
            require_selected_chains(cases, requested)
            cases = [by_key[key] for key in requested]
    except StartingStateError as exc:
        raise ValueError(f"QA plan {plan['slug']!r}: {exc}") from exc
    if not cases:
        raise ValueError(f"QA plan {plan_id} has no runnable cases")
    return {"plan": plan, "cases": cases}


def validate_flow_plan_references(
    conn: Any,
    *,
    project_id: int,
    stages: list[dict[str, Any]],
) -> None:
    """Validate project-owned reusable plans selected by QA stages."""
    if not _table_exists(conn, "qa_plans"):
        for stage in stages:
            if isinstance(stage.get("cases"), Mapping):
                raise LookupError("QA plan catalog is not installed")
        return
    for stage in stages:
        cases = stage.get("cases")
        if not isinstance(cases, Mapping):
            continue
        _plan_snapshot(
            conn,
            int(cases["plan_id"]),
            project_id=project_id,
            case_keys=cases.get("case_keys"),
        )


def _requirement_snapshot(
    conn: Any,
    *,
    run_id: str,
    item_id: int,
    requirement_id: int,
    admission,
) -> dict[str, Any] | None:
    raw_requirement = admission.requirements.get(requirement_id)
    if raw_requirement is None:
        raise LookupError(f"QA requirement {requirement_id} not found")
    requirement = semantic_row(raw_requirement, REQUIREMENT_FIELDS)
    bound_run = str(requirement.get("deployment_run_id") or "")
    if bound_run and bound_run != run_id:
        raise ValueError(
            f"QA requirement {requirement_id} belongs to deployment run "
            f"{bound_run!r}, not {run_id!r}"
        )
    if int(requirement.get("item_id") or 0) != int(item_id):
        raise ValueError(
            f"QA requirement {requirement_id} is not owned by {render_item_ref(conn, item_id)}"
        )
    if raw_requirement.get("waived_at") is not None:
        raise ValueError(f"QA requirement {requirement_id} is waived")
    if raw_requirement.get("retracted_at") is not None:
        return None
    return requirement


def snapshot_member_requirements(
    conn: Any,
    *,
    run_id: str,
    item_id: int,
    selection_json: Any,
    admission=None,
) -> str:
    """Freeze a member's explicitly selected item cases."""
    from yoke_core.domain.deployment_admission_reads import read_snapshot_inputs

    selected = _selection(selection_json)
    if admission is None:
        admission = read_snapshot_inputs(
            conn,
            item_ids=(item_id,),
            requirement_ids=selected["requirement_ids"],
        )
    requirements = []
    for requirement_id in selected["requirement_ids"]:
        requirement = _requirement_snapshot(
            conn,
            run_id=run_id,
            item_id=item_id,
            requirement_id=requirement_id,
            admission=admission,
        )
        # Plans run as plan groups at item QA; a member freezes only its
        # own item cases (an older build's plan copy is history, not intake).
        if requirement is not None and requirement.get("plan_id") is None:
            requirements.append(requirement)
    payload = {
        "schema": SNAPSHOT_SCHEMA,
        "selection": selected,
        "requirements": requirements,
    }
    return _canonical(payload)


def snapshot_members_requirements(
    conn: Any, *, run_id: str, selections: Mapping[int, Any], lock: bool = True
) -> dict[int, str]:
    """Snapshot every member's selection from one read; ``lock`` holds its rows."""
    from yoke_core.domain.deployment_admission_reads import read_snapshot_inputs

    parsed = {int(item_id): _selection(raw) for item_id, raw in selections.items()}
    admission = read_snapshot_inputs(
        conn,
        item_ids=parsed,
        requirement_ids=[v for s in parsed.values() for v in s["requirement_ids"]],
        lock=lock,
    )
    return {
        item_id: snapshot_member_requirements(
            conn,
            run_id=run_id,
            item_id=item_id,
            selection_json=selections[item_id],
            admission=admission,
        )
        for item_id in parsed
    }


def snapshot_flow_requirements(
    conn: Any,
    *,
    flow_id: str,
    project_id: int,
    stages: list[dict[str, Any]],
) -> str:
    """Freeze mutable plan content referenced by an immutable flow."""
    selections: list[dict[str, Any]] = []
    for stage in stages:
        cases = stage.get("cases")
        if not isinstance(cases, Mapping):
            continue
        selections.append(
            {
                "stage": str(stage["name"]),
                **_plan_snapshot(
                    conn,
                    int(cases["plan_id"]),
                    project_id=project_id,
                    case_keys=cases.get("case_keys"),
                ),
            }
        )
    payload = {
        "schema": SNAPSHOT_SCHEMA,
        "flow_id": flow_id,
        "selections": selections,
    }
    return _canonical(payload)


__all__ = [
    "requirement_selection",
    "snapshot_flow_requirements",
    "snapshot_member_requirements",
    "snapshot_members_requirements",
    "validate_flow_plan_references",
]
