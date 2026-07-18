"""Project-owned declarative deployment-flow reconciliation.

External project repositories carry their delivery definitions in
``.yoke/deployment-flows.json``. This module validates that document and
converges only the definitions it declares. Omitted rows are deliberately
left untouched so old definitions and deployment-run history remain readable.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import json_helper
from yoke_core.domain import deploy_defaults
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_flow_state import (
    FLOW_STATUS_ACTIVE,
    assert_flow_definition_mutable,
)
from yoke_core.domain.deployment_flow_declaration_schema import (
    FlowDeclaration,
    FlowDeclarationDocument,
    empty_declaration_text,
    normalize_document,
)
from yoke_core.domain.flow_cross_reference import (
    _validate_flow_stages_cross_reference,
)
from yoke_core.domain.project_identity import resolve_project
from yoke_contracts.project_contract.deployment_flows import (
    DECLARATION_RELATIVE_PATH,
    DECLARATION_SCHEMA,
)


_DEFINITION_FIELDS = (
    "name",
    "description",
    "stages",
    "on_failure",
    "target_env",
    "done_description",
)


def reconcile_project_flows(
    conn: Any,
    project: str,
    document: object,
    *,
    preview_only: bool = False,
) -> dict[str, Any]:
    """Add or safely update declared flows for one project.

    A definition used by any deployment run is immutable. Status remains a
    lifecycle switch and may still converge. Rows omitted from the document
    are never disabled or deleted.
    """
    normalized = normalize_document(document)
    ident = resolve_project(conn, project)
    assert ident is not None

    for flow in normalized.flows:
        _validate_flow_stages_cross_reference(
            conn, ident.id, flow.stages, flow_id=flow.id,
        )

    created: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []
    retired: list[str] = []
    retire_absent: list[str] = []
    retire_unchanged: list[str] = []
    default_flow_updated = False
    try:
        for flow in normalized.flows:
            row = conn.execute(
                "SELECT project_id, name, description, stages, on_failure, "
                "target_env, done_description, status "
                "FROM deployment_flows WHERE id=%s",
                (flow.id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO deployment_flows "
                    "(id, project_id, name, description, stages, on_failure, "
                    "target_env, done_description, status, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        flow.id,
                        ident.id,
                        flow.name,
                        flow.description,
                        flow.stages,
                        flow.on_failure,
                        flow.target_env,
                        flow.done_description,
                        flow.status,
                        iso8601_now(),
                    ),
                )
                created.append(flow.id)
                continue
            if int(row[0]) != ident.id:
                raise ValueError(
                    f"deployment flow '{flow.id}' belongs to another project"
                )
            existing = {
                "name": row[1],
                "description": row[2] or "",
                "stages": row[3],
                "on_failure": row[4],
                "target_env": row[5],
                "done_description": row[6],
                "status": row[7],
            }
            desired = flow.__dict__
            definition_changed = any(
                not _field_equal(field, existing[field], desired[field])
                for field in _DEFINITION_FIELDS
            )
            status_changed = str(existing["status"]) != flow.status
            if not definition_changed and not status_changed:
                unchanged.append(flow.id)
                continue
            if definition_changed:
                assert_flow_definition_mutable(conn, flow.id)
            conn.execute(
                "UPDATE deployment_flows SET name=%s, description=%s, "
                "stages=%s, on_failure=%s, target_env=%s, "
                "done_description=%s, status=%s WHERE id=%s",
                (
                    flow.name,
                    flow.description,
                    flow.stages,
                    flow.on_failure,
                    flow.target_env,
                    flow.done_description,
                    flow.status,
                    flow.id,
                ),
            )
            updated.append(flow.id)
        for flow_id in normalized.retire_if_present:
            row = conn.execute(
                "SELECT project_id, status FROM deployment_flows WHERE id=%s",
                (flow_id,),
            ).fetchone()
            if row is None:
                retire_absent.append(flow_id)
                continue
            if int(row[0]) != ident.id:
                raise ValueError(
                    f"retirement flow '{flow_id}' belongs to another project"
                )
            if str(row[1]) != FLOW_STATUS_ACTIVE:
                retire_unchanged.append(flow_id)
                continue
            conn.execute(
                "UPDATE deployment_flows SET status='disabled' WHERE id=%s",
                (flow_id,),
            )
            retired.append(flow_id)
        if normalized.default_flow_declared:
            row = conn.execute(
                "SELECT project_id, status FROM deployment_flows WHERE id=%s",
                (normalized.default_flow,),
            ).fetchone()
            if row is None or int(row[0]) != ident.id:
                raise ValueError(
                    f"default_flow '{normalized.default_flow}' is not a flow "
                    f"for project '{ident.slug}'"
                )
            if str(row[1]) != FLOW_STATUS_ACTIVE:
                raise ValueError(
                    f"default_flow '{normalized.default_flow}' must be active"
                )
            default_flow_updated = deploy_defaults.set_default_flow_on_connection(
                conn,
                ident.slug,
                str(normalized.default_flow),
            )
        if preview_only:
            conn.rollback()
        else:
            conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {
        "project": ident.slug,
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "retired": retired,
        "retire_absent": retire_absent,
        "retire_unchanged": retire_unchanged,
        "default_flow": normalized.default_flow,
        "default_flow_declared": normalized.default_flow_declared,
        "default_flow_updated": default_flow_updated and not preview_only,
        "preview_only": preview_only,
    }


def _field_equal(field: str, existing: object, desired: object) -> bool:
    if field != "stages":
        return existing == desired
    try:
        return json_helper.loads_text(str(existing)) == json_helper.loads_text(
            str(desired)
        )
    except ValueError:
        return existing == desired


__all__ = [
    "DECLARATION_RELATIVE_PATH",
    "DECLARATION_SCHEMA",
    "FlowDeclaration",
    "FlowDeclarationDocument",
    "empty_declaration_text",
    "normalize_document",
    "reconcile_project_flows",
]
