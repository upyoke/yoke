"""Read models for the QA method, plan, and activity experience."""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_contracts.machine_config.capability_secrets import (
    TEST_MACHINE_CAPABILITY,
)
from yoke_contracts.item_ref import format_item_ref
from yoke_core.domain import db_backend
from yoke_core.domain.capabilities_list_read import (
    STATE_CONFIGURED_UNVERIFIED,
    STATE_ERROR,
    STATE_IN_USE,
    STATE_READY,
)
from yoke_core.domain.capabilities_test_machine_read import (
    read_test_machine_facts,
)
from yoke_core.domain.db_helpers import query_one, query_rows, query_scalar
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.qa_activity_reads import list_activity, read_activity
from yoke_core.domain.qa_execution_proof import qa_run_outcome
from yoke_core.domain.qa_method_related_plans import read_method_related_plans
from yoke_core.domain.workflow_runtime import workflow_runtime_from_row

# Retained for the plan-detail reader while proof helpers converge on the
# dedicated execution-proof module.
_outcome = qa_run_outcome


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _json_value(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return fallback


def _project_row(conn: Any, project: Optional[str]) -> Optional[Any]:
    if project is None:
        return None
    identity = resolve_project(conn, project, required=False)
    if identity is None:
        raise LookupError(f"project {project!r} not found")
    return identity


def _capability_contexts(
    conn: Any,
    *,
    project_id: Optional[int],
    capability_kinds: set[Optional[str]],
) -> dict[Optional[str], dict[str, Any]]:
    """Return one truthful readiness projection per capability kind."""
    contexts: dict[Optional[str], dict[str, Any]] = {
        None: {"state": "available"},
    }
    kinds = sorted(str(kind) for kind in capability_kinds if kind)
    if not kinds:
        return contexts
    if project_id is None:
        contexts.update({kind: {"state": "project_scoped"} for kind in kinds})
        return contexts
    marker = _placeholder(conn)
    markers = ", ".join([marker] * len(kinds))
    rows = query_rows(
        conn,
        "SELECT type, verified_at FROM project_capabilities "
        f"WHERE project_id={marker} AND type IN ({markers})",
        (project_id, *kinds),
    )
    declarations = {str(row["type"]): row["verified_at"] for row in rows}
    contexts.update(
        {
            kind: {
                "state": (
                    STATE_READY
                    if declarations.get(kind)
                    else "configured"
                    if kind in declarations
                    else "not_configured"
                ),
            }
            for kind in kinds
        }
    )
    if (
        TEST_MACHINE_CAPABILITY not in kinds
        or TEST_MACHINE_CAPABILITY not in declarations
    ):
        return contexts
    verification, active_items, _method_count = read_test_machine_facts(
        conn,
        [project_id],
    )
    machine = contexts[TEST_MACHINE_CAPABILITY]
    machine["concurrency_mode"] = "serial"
    if project_id in active_items:
        machine.update(
            {
                "state": STATE_IN_USE,
                "wait_reason": "serial_lease_in_use",
                "active_lease": {
                    "item_ref": active_items[project_id],
                },
            }
        )
    elif verification.get(project_id) == STATE_ERROR:
        machine["state"] = STATE_ERROR
    elif verification.get(project_id) == "verified":
        machine["state"] = STATE_READY
    elif verification.get(project_id) == STATE_CONFIGURED_UNVERIFIED:
        machine["state"] = STATE_CONFIGURED_UNVERIFIED
    elif not declarations.get(TEST_MACHINE_CAPABILITY):
        machine["state"] = STATE_CONFIGURED_UNVERIFIED
    return contexts


def list_methods(conn: Any, *, project: Optional[str] = None) -> list[dict]:
    """Return contracts plus derived usage and capability availability."""
    identity = _project_row(conn, project)
    project_id = int(identity.id) if identity is not None else None
    marker = _placeholder(conn)
    rows = query_rows(
        conn,
        "SELECT * FROM qa_methods "
        "WHERE project_id IS NULL"
        + (f" OR project_id={marker}" if project_id is not None else "")
        + " ORDER BY "
        "CASE WHEN required_capability_kind IS NULL THEN 0 "
        "WHEN required_capability_kind='browser-control' THEN 1 ELSE 2 END, "
        "name",
        (project_id,) if project_id is not None else (),
    )
    capability_contexts = _capability_contexts(
        conn,
        project_id=project_id,
        capability_kinds={row["required_capability_kind"] for row in rows},
    )
    result = []
    for row in rows:
        count_params: tuple = (row["id"],)
        count_sql = (
            "SELECT COUNT(DISTINCT c.plan_id) "
            "FROM qa_plan_cases c JOIN qa_plans p ON p.id=c.plan_id "
            f"WHERE c.method_id={marker} AND p.retired_at IS NULL"
        )
        if project_id is not None:
            count_sql += f" AND p.project_id={marker}"
            count_params += (project_id,)
        used_by = int(query_scalar(conn, count_sql, count_params) or 0)
        capability_kind = row["required_capability_kind"]
        capability_context = dict(capability_contexts[capability_kind])
        result.append(
            {
                "id": str(row["id"]),
                "name": str(row["name"]),
                "description": str(row["description"]),
                "source_kind": str(row["source_kind"]),
                "source_ref": row["source_ref"],
                "executor_id": str(row["executor_id"]),
                "required_capability_kind": capability_kind,
                "verdict_path": str(row["verdict_path"]),
                "verdict_contract": str(row["verdict_contract"]),
                "evidence_contract": str(row["evidence_contract"]),
                "success_policy_id": str(row["success_policy_id"]),
                "success_policy_params": _json_value(
                    row["success_policy_params"],
                    {},
                ),
                "concurrency_mode": str(row["concurrency_mode"]),
                "used_by_plan_count": used_by,
                "capability_state": capability_context["state"],
                "capability_context": capability_context,
            }
        )
    return result


def get_method(
    conn: Any,
    *,
    method_id: str,
    project: Optional[str] = None,
) -> dict:
    rows = list_methods(conn, project=project)
    method = next((row for row in rows if row["id"] == method_id), None)
    if method is None:
        raise LookupError(f"QA method {method_id!r} not found")
    identity = _project_row(conn, project)
    plans = read_method_related_plans(
        conn,
        method_id=method_id,
        project_id=int(identity.id) if identity is not None else None,
    )
    return {**method, "plans": plans}


def _latest_requirement_outcome(conn: Any, plan_id: int) -> tuple:
    marker = _placeholder(conn)
    row = query_one(
        conn,
        "SELECT q.id, q.waived_at, r.verdict, r.case_outcome, "
        "COALESCE(r.completed_at, r.created_at, q.created_at) AS happened_at "
        "FROM qa_requirements q "
        "LEFT JOIN qa_runs r ON r.id=("
        "SELECT rr.id FROM qa_runs rr "
        "WHERE rr.qa_requirement_id=q.id "
        "ORDER BY rr.created_at DESC, rr.id DESC LIMIT 1"
        ") "
        f"WHERE q.plan_id={marker} "
        "ORDER BY happened_at DESC, q.id DESC LIMIT 1",
        (plan_id,),
    )
    if row is None:
        return (None, None)
    return (qa_run_outcome(row), row["happened_at"])


def _attachment_rows(conn: Any, plan_id: int) -> list[dict]:
    marker = _placeholder(conn)
    project_defaults = query_rows(
        conn,
        "SELECT 'project_default' AS kind, p.slug AS project, "
        "d.workflow_id, d.transition_id, NULL AS item_id, "
        "v.id AS workflow_version_id, v.version, "
        "v.definition_json, v.definition_digest "
        "FROM qa_plan_project_defaults d "
        "JOIN projects p ON p.id=d.project_id "
        "JOIN workflows w ON w.id=d.workflow_id "
        "JOIN workflow_versions v ON v.id=w.current_version_id "
        f"WHERE d.plan_id={marker} "
        "ORDER BY p.slug, d.workflow_id, d.transition_id",
        (plan_id,),
    )
    item_attachments = query_rows(
        conn,
        "SELECT 'item' AS kind, p.slug AS project, "
        "i.workflow_id, a.transition_id, i.id AS item_id, "
        "p.public_item_prefix, i.project_sequence, "
        "v.id AS workflow_version_id, v.version, "
        "v.definition_json, v.definition_digest "
        "FROM qa_plan_item_attachments a "
        "JOIN items i ON i.id=a.item_id "
        "JOIN projects p ON p.id=i.project_id "
        "JOIN workflow_versions v ON v.id=i.workflow_version_id "
        f"WHERE a.plan_id={marker} "
        "ORDER BY p.slug, i.id, a.transition_id",
        (plan_id,),
    )
    result = []
    for raw in [*project_defaults, *item_attachments]:
        row = dict(raw)
        runtime = workflow_runtime_from_row(row)
        row["transition_label"] = runtime.stage_label(
            str(row["transition_id"]),
        )
        for key in (
            "workflow_version_id",
            "version",
            "definition_json",
            "definition_digest",
        ):
            row.pop(key)
        if row["kind"] == "item":
            prefix = row.pop("public_item_prefix")
            sequence = row.pop("project_sequence")
            row["item_ref"] = format_item_ref(
                row["project"],
                prefix,
                sequence,
                item_id=int(row["item_id"]),
            )
        result.append(row)
    return result


def list_plans(conn: Any, *, project: Optional[str] = None) -> list[dict]:
    identity = _project_row(conn, project)
    marker = _placeholder(conn)
    params: tuple = ()
    where = "WHERE p.retired_at IS NULL"
    if identity is not None:
        where += f" AND p.project_id={marker}"
        params = (int(identity.id),)
    rows = query_rows(
        conn,
        "SELECT p.*, pr.slug AS project FROM qa_plans p "
        f"JOIN projects pr ON pr.id=p.project_id {where} "
        "ORDER BY pr.slug, p.slug",
        params,
    )
    result = []
    for row in rows:
        plan_id = int(row["id"])
        cases = query_rows(
            conn,
            "SELECT method_id, host_baselines FROM qa_plan_cases "
            f"WHERE plan_id={marker} ORDER BY position",
            (plan_id,),
        )
        materialized_count = sum(
            max(1, len(_json_value(case["host_baselines"], []))) for case in cases
        )
        last_outcome, last_at = _latest_requirement_outcome(conn, plan_id)
        result.append(
            {
                "id": plan_id,
                "project": str(row["project"]),
                "slug": str(row["slug"]),
                "name": str(row["name"]),
                "description": str(row["description"]),
                "case_count": len(cases),
                "materialized_requirement_count": materialized_count,
                "method_ids": list(
                    dict.fromkeys(str(case["method_id"]) for case in cases)
                ),
                "attachments": _attachment_rows(conn, plan_id),
                "last_outcome": last_outcome,
                "last_at": last_at,
            }
        )
    return result


__all__ = [
    "get_method",
    "list_activity",
    "list_methods",
    "list_plans",
    "read_activity",
]
