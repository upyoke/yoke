"""Correct live QA case configuration without replacing the requirement.

Frozen deployment-run rows and historical ``qa_runs`` stay immutable. An
in-place ``method_config`` change records a revision marker; a later green
satisfies only when it recorded that live executable config at run start.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_constants import (
    VALID_BLOCKING_MODES,
    VALID_QA_PHASES,
    _normalize_qa_phase,
)
from yoke_core.domain.qa_method_capabilities import (
    QaMethodCapabilityError,
    encoded_capability_kinds,
)
from yoke_core.domain.qa_method_config_validation import (
    QaMethodConfigError,
    validate_method_config,
)
from yoke_core.domain.qa_method_definitions import BUILTIN_QA_METHODS
from yoke_core.domain.qa_plan_execution_store import canonical
from yoke_core.domain.qa_requirement_pass_currency import (
    METHOD_CONFIG_FIELD,
    _marker,
    bind_correction_identity,
    executable_method_config,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists


FROZEN_REQUIREMENT_CODE = "frozen_requirement_immutable"
FROZEN_REQUIREMENT_MESSAGE = (
    "frozen_requirement_immutable: a deployment-run requirement is a frozen "
    "acceptance snapshot and cannot be corrected in place. Update the live "
    "item requirement, then re-run it. Recovery: yoke qa requirement update "
    "--requirement-id <live-id> --field method_config --value '<json>'"
)

UPDATABLE_REQUIREMENT_FIELDS: tuple[str, ...] = (
    "success_policy",
    "blocking_mode",
    "target_env",
    "capability_requirements",
    "suite_id",
    "qa_phase",
    METHOD_CONFIG_FIELD,
)

_BUILTIN_CONTRACTS = {
    str(method["id"]): str(method["config_contract_id"])
    for method in BUILTIN_QA_METHODS
}


@dataclass(frozen=True)
class RequirementUpdateResult:
    """Outcome of one ``qa.requirement.update`` attempt."""

    ok: bool
    error_code: str = ""
    message: str = ""
    jsonpath: str = "$.payload.field"
    requirement_id: int = 0
    field: str = ""
    new_value: Any = None


def _fail(
    *,
    code: str,
    message: str,
    req_id: int,
    field: str,
    jsonpath: str = "$.payload.field",
) -> RequirementUpdateResult:
    return RequirementUpdateResult(
        ok=False,
        error_code=code,
        message=message,
        jsonpath=jsonpath,
        requirement_id=int(req_id),
        field=field,
    )


def _config_contract_id(conn: Any, method_id: str) -> str | None:
    if _table_exists(conn, "qa_methods"):
        method = query_one(
            conn,
            f"SELECT config_contract_id FROM qa_methods WHERE id={_marker(conn)}",
            (str(method_id),),
        )
        if method is not None and method["config_contract_id"]:
            return str(method["config_contract_id"])
    return _BUILTIN_CONTRACTS.get(str(method_id))


def _prepare_method_config(
    conn: Any, existing: Any, value: Any
) -> tuple[Optional[str], str]:
    method_id = str(existing["method_id"] or "") if existing["method_id"] else ""
    if not method_id:
        return None, "method_config is only updatable on method-backed requirements"
    if existing["deployment_run_id"]:
        return None, FROZEN_REQUIREMENT_MESSAGE
    contract_id = _config_contract_id(conn, method_id)
    if contract_id is None:
        return None, f"method {method_id!r} is not registered"
    raw: Any = value
    if isinstance(value, str):
        try:
            raw = json.loads(value)
        except (TypeError, ValueError):
            return None, "method_config must be a JSON object"
    if isinstance(raw, dict):
        raw = executable_method_config(raw)
    try:
        config = validate_method_config(contract_id, raw)
    except QaMethodConfigError as exc:
        return None, str(exc)
    return canonical(config), ""


def _prepare_target_env(
    conn: Any, existing: Any, value: Any
) -> tuple[Optional[tuple[Any, ...]], str]:
    run_id = existing["deployment_run_id"]
    project_id = None
    if run_id:
        run = query_one(
            conn,
            f"SELECT status, composition_frozen_at, project_id "
            f"FROM deployment_runs WHERE id={_marker(conn)}",
            (str(run_id),),
        )
        if run is None or str(run["status"] or "") != "created" or str(
            run["composition_frozen_at"] or existing.get("execution_target_digest") or ""
        ).strip():
            return None, FROZEN_REQUIREMENT_MESSAGE
        project_id = int(run["project_id"])
    name = str(value or "").strip() or None
    from yoke_core.domain.qa_environment_execution_target import (
        persistable_named_environment_target,
    )
    from yoke_core.domain.qa_execution_environment_target import (
        QaExecutionTargetError,
        canonical_target,
        target_digest,
    )

    owner = (
        existing["item_id"]
        if existing["item_id"] is not None
        else existing["epic_id"]
    )
    if owner is not None and project_id is None and _table_exists(conn, "items"):
        project_row = query_one(
            conn,
            f"SELECT project_id FROM items WHERE id={_marker(conn)}",
            (int(owner),),
        )
        if project_row is not None and project_row["project_id"] is not None:
            project_id = int(project_row["project_id"])
    if name and project_id is None and _table_exists(conn, "environments"):
        return None, (
            "requirement has no project to resolve an execution target against"
        )
    try:
        snapshot = None
        if name and project_id is not None and _table_exists(conn, "environments"):
            snapshot = persistable_named_environment_target(
                conn, project_id=int(project_id), environment_name=name
            )
    except QaExecutionTargetError as exc:
        return None, str(exc)
    target_json = canonical_target(snapshot) if snapshot else None
    digest = target_digest(snapshot) if snapshot else None
    return (name, target_json, digest), ""


def apply_requirement_update(
    conn: Any,
    req_id: int,
    field: str,
    value: Any,
    *,
    db_path: Optional[str] = None,
) -> RequirementUpdateResult:
    """Validate and persist one mutable QA requirement field."""
    from yoke_core.domain.qa_events import emit_qa_requirement_event

    if field == "qa_kind":
        return _fail(
            code="field_not_updatable",
            message=(
                "qa_kind is not updatable; use requirement-waive + requirement-add"
            ),
            req_id=req_id,
            field=field,
        )
    if field not in UPDATABLE_REQUIREMENT_FIELDS:
        return _fail(
            code="field_not_updatable",
            message=(
                f"field {field!r} is not updatable; allowed: "
                f"{', '.join(UPDATABLE_REQUIREMENT_FIELDS)}"
            ),
            req_id=req_id,
            field=field,
        )
    if field == "blocking_mode" and value not in VALID_BLOCKING_MODES:
        return _fail(
            code="payload_invalid",
            message=f"blocking_mode must be one of {sorted(VALID_BLOCKING_MODES)}",
            req_id=req_id,
            field=field,
            jsonpath="$.payload.value",
        )
    if field == "qa_phase":
        normalized = _normalize_qa_phase(str(value or ""))
        if normalized not in VALID_QA_PHASES:
            return _fail(
                code="payload_invalid",
                message=f"qa_phase must be one of {sorted(VALID_QA_PHASES)}",
                req_id=req_id,
                field=field,
                jsonpath="$.payload.value",
            )
        value = normalized
    if field == "capability_requirements":
        try:
            value = encoded_capability_kinds(value, subject="QA requirement")
        except QaMethodCapabilityError as exc:
            return _fail(
                code="payload_invalid",
                message=str(exc),
                req_id=req_id,
                field=field,
                jsonpath="$.payload.value",
            )

    marker = _marker(conn)
    digest_col = (
        ", execution_target_digest"
        if _column_exists(conn, "qa_requirements", "execution_target_digest")
        else ""
    )
    existing = query_one(
        conn,
        "SELECT qa_kind, qa_phase, item_id, epic_id, task_num, "
        f"deployment_run_id, method_id, method_config{digest_col} "
        f"FROM qa_requirements WHERE id = {marker}",
        (int(req_id),),
    )
    if existing is None:
        return _fail(
            code="not_found",
            message=f"requirement {req_id} not found",
            req_id=req_id,
            field=field,
        )
    if field == METHOD_CONFIG_FIELD:
        prepared, error = _prepare_method_config(conn, existing, value)
        if error:
            code = (
                FROZEN_REQUIREMENT_CODE
                if error.startswith(FROZEN_REQUIREMENT_CODE)
                else "payload_invalid"
            )
            return _fail(
                code=code,
                message=error,
                req_id=req_id,
                field=field,
                jsonpath="$.payload.value",
            )
        value = bind_correction_identity(existing["method_config"], prepared)
    if field == "target_env":
        prepared, error = _prepare_target_env(conn, existing, value)
        if error:
            code = (
                FROZEN_REQUIREMENT_CODE
                if error.startswith(FROZEN_REQUIREMENT_CODE)
                else "payload_invalid"
            )
            return _fail(
                code=code,
                message=error,
                req_id=req_id,
                field=field,
                jsonpath="$.payload.value",
            )
        name, target_json, digest = prepared
        conn.execute(
            f"UPDATE qa_requirements SET target_env = {marker} WHERE id = {marker}",
            (name, int(req_id)),
        )
        from yoke_core.domain.qa_environment_execution_target import (
            persist_requirement_target_snapshot,
        )

        persist_requirement_target_snapshot(
            conn, int(req_id),
            {"execution_target_json": target_json, "execution_target_digest": digest},
        )
        value = name
    else:
        conn.execute(
            f"UPDATE qa_requirements SET {field} = {marker} WHERE id = {marker}",
            (value, int(req_id)),
        )
    event_phase = value if field == "qa_phase" else str(existing["qa_phase"])
    conn.commit()
    emit_qa_requirement_event(
        conn,
        db_path=db_path,
        event_name="QARequirementUpdated",
        requirement_id=int(req_id),
        qa_kind=str(existing["qa_kind"]),
        qa_phase=event_phase,
        extra_detail={"field": field, "new_value": value},
        target_row=existing,
    )
    return RequirementUpdateResult(
        ok=True,
        requirement_id=int(req_id),
        field=field,
        new_value=value,
    )


__all__ = [
    "FROZEN_REQUIREMENT_CODE",
    "FROZEN_REQUIREMENT_MESSAGE",
    "METHOD_CONFIG_FIELD",
    "RequirementUpdateResult",
    "UPDATABLE_REQUIREMENT_FIELDS",
    "apply_requirement_update",
]
