"""Immutable QA inputs captured when a deployment run starts."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_requirement_snapshot_format import (
    CASE_FIELDS,
    PLAN_FIELDS,
    REQUIREMENT_FIELDS,
    semantic_row,
)
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.qa_plan_attachment_reads import live_item_attachment_sql
from yoke_core.domain.project_identity import render_item_ref
from yoke_contracts.public_ref import ITEM_NOT_FOUND


SNAPSHOT_SCHEMA = 1
SELECTION_SCHEMA = 1


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _row_dict(cursor: Any, row: Any) -> dict[str, Any]:
    if hasattr(row, "keys"):
        return {str(key): row[key] for key in row.keys()}
    columns = [str(getattr(col, "name", None) or col[0]) for col in cursor.description]
    return dict(zip(columns, row))


def _positive_ids(values: Iterable[Any], *, field: str) -> list[int]:
    normalized: list[int] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} must contain positive integer ids")
        normalized.append(int(value))
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field} must not contain duplicate ids")
    return sorted(normalized)


def requirement_selection(
    *,
    requirement_ids: Iterable[int] = (),
    plan_ids: Iterable[int] = (),
) -> str:
    """Encode an explicit per-member requirement selection."""
    return _canonical(
        {
            "schema": SELECTION_SCHEMA,
            "requirement_ids": _positive_ids(requirement_ids, field="requirement_ids"),
            "plan_ids": _positive_ids(plan_ids, field="plan_ids"),
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
        "plan_ids": _positive_ids(decoded.get("plan_ids") or [], field="plan_ids"),
    }


def _plan_snapshot(
    conn: Any,
    plan_id: int,
    *,
    project_id: int,
    case_keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    marker = _p(conn)
    lock = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    cursor = conn.execute(
        f"SELECT {','.join(PLAN_FIELDS)},retired_at "
        f"FROM qa_plans WHERE id={marker}{lock}",
        (int(plan_id),),
    )
    row = cursor.fetchone()
    if row is None:
        raise LookupError(f"QA plan {plan_id} not found")
    raw_plan = _row_dict(cursor, row)
    plan = semantic_row(raw_plan, PLAN_FIELDS)
    if int(plan["project_id"]) != int(project_id):
        raise ValueError(f"QA plan {plan_id} belongs to another project")
    if raw_plan.get("retired_at") is not None:
        raise ValueError(f"QA plan {plan_id} is retired")
    requested = [str(value) for value in (case_keys or ())]
    if any(not value for value in requested) or len(requested) != len(set(requested)):
        raise ValueError(f"QA plan {plan_id} case_keys must be unique non-empty names")
    cursor = conn.execute(
        "SELECT c.id,c.plan_id,c.case_key,c.position,c.method_id,c.instructions,"
        "c.expected_outcome,c.method_config,c.success_policy_id,"
        "c.success_policy_params,c.host_baselines,c.entry_surface,"
        "c.required_completion,m.name AS method_name,m.runner_id,"
        "m.required_capability_kinds,m.verdict_path,m.config_contract_id "
        "FROM qa_plan_cases c JOIN qa_methods m ON m.id=c.method_id "
        f"WHERE c.plan_id={marker} ORDER BY c.position,c.id",
        (int(plan_id),),
    )
    cases = [
        semantic_row(_row_dict(cursor, raw), CASE_FIELDS) for raw in cursor.fetchall()
    ]
    if requested:
        by_key = {str(case["case_key"]): case for case in cases}
        missing = sorted(set(requested) - set(by_key))
        if missing:
            raise LookupError(f"QA plan {plan_id} has no cases: {missing}")
        cases = [by_key[key] for key in requested]
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
) -> dict[str, Any]:
    marker = _p(conn)
    lock = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    cursor = conn.execute(
        f"SELECT {','.join(REQUIREMENT_FIELDS)},waived_at "
        f"FROM qa_requirements WHERE id={marker}{lock}",
        (int(requirement_id),),
    )
    row = cursor.fetchone()
    if row is None:
        raise LookupError(f"QA requirement {requirement_id} not found")
    raw_requirement = _row_dict(cursor, row)
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
    return requirement


def snapshot_member_requirements(
    conn: Any,
    *,
    run_id: str,
    item_id: int,
    selection_json: Any,
) -> str:
    """Freeze explicitly selected member requirements and attached plans."""
    selected = _selection(selection_json)
    if not _table_exists(conn, "qa_requirements") and selected["requirement_ids"]:
        raise LookupError("QA requirement catalog is not installed")
    requirements = [
        _requirement_snapshot(
            conn,
            run_id=run_id,
            item_id=item_id,
            requirement_id=requirement_id,
        )
        for requirement_id in selected["requirement_ids"]
    ]
    item_row = conn.execute(
        f"SELECT project_id FROM items WHERE id={_p(conn)}", (int(item_id),)
    ).fetchone()
    if item_row is None:
        raise LookupError(ITEM_NOT_FOUND)
    project_id = int(
        item_row["project_id"] if hasattr(item_row, "keys") else item_row[0]
    )
    plans: list[dict[str, Any]] = []
    for plan_id in selected["plan_ids"]:
        attached = conn.execute(
            f"SELECT transition_id,qa_phase FROM qa_plan_item_attachments "
            f"WHERE item_id={_p(conn)} AND plan_id={_p(conn)} "
            f"AND {live_item_attachment_sql(conn)}",
            (int(item_id), int(plan_id)),
        ).fetchone()
        if attached is None:
            raise ValueError(
                f"QA plan {plan_id} is not attached to {render_item_ref(conn, item_id)}; attach it "
                "before selecting it for release admission"
            )
        plans.append(
            {
                "attachment": {
                    "transition_id": str(
                        attached["transition_id"]
                        if hasattr(attached, "keys")
                        else attached[0]
                    ),
                    "qa_phase": str(
                        attached["qa_phase"]
                        if hasattr(attached, "keys")
                        else attached[1]
                    ),
                },
                **_plan_snapshot(conn, plan_id, project_id=project_id),
            }
        )
    payload = {
        "schema": SNAPSHOT_SCHEMA,
        "selection": selected,
        "requirements": requirements,
        "plans": plans,
    }
    return _canonical(payload)


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
    "validate_flow_plan_references",
]
