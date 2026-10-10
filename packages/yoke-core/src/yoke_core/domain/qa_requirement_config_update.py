"""Correct live QA case configuration without replacing the requirement.

Frozen deployment-run rows and historical ``qa_runs`` stay immutable. An
in-place ``method_config`` change records a revision marker; a later green
satisfies only when it recorded that live executable config at run start.

Two fields need more than a validated write and live in sibling modules:
``target_env`` resolves an environment name into an immutable endpoint
snapshot, and ``workflow_transition_id`` revalidates the lifecycle binding
exactly as a fresh attachment would.
"""

from __future__ import annotations

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
from yoke_core.domain.qa_requirement_target_env_update import (
    _prepare_target_env,
)
from yoke_core.domain.qa_requirement_transition_update import (
    _prepare_workflow_transition,
)
from yoke_core.domain.qa_requirement_method_config_update import (
    _prepare_method_config,
)
from yoke_core.domain.qa_replacement_scope_guard import (
    LINK_SCOPE_FIELDS,
    LINKED_SCOPE_CHANGE_CODE,
    linked_scope_refusal,
)
from yoke_core.domain.qa_requirement_pass_currency import (
    METHOD_CONFIG_FIELD,
    _marker,
    bind_correction_identity,
)
from yoke_core.domain.qa_admitted_case_reconciliation import (
    ADMITTED_COPY_IN_FLIGHT_CODE,
    reconcile_admitted_copies,
)
from yoke_core.domain.qa_requirement_frozen_snapshot import (
    FROZEN_REQUIREMENT_CODE,
    FROZEN_REQUIREMENT_MESSAGE,
)
from yoke_core.domain.schema_common import _column_exists


UPDATABLE_REQUIREMENT_FIELDS: tuple[str, ...] = (
    "success_policy",
    "blocking_mode",
    "target_env",
    "capability_requirements",
    "suite_id",
    "qa_phase",
    "workflow_transition_id",
    METHOD_CONFIG_FIELD,
)


@dataclass(frozen=True)
class RequirementUpdateResult:
    """Outcome of one ``qa.requirement.update`` attempt."""

    ok: bool
    admitted_copies_updated: tuple[int, ...] = ()
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
        "SELECT id, qa_kind, qa_phase, item_id, epic_id, task_num, "
        f"deployment_run_id, plan_id, method_id, method_config{digest_col} "
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
    if field == "workflow_transition_id":
        prepared_transition, error = _prepare_workflow_transition(conn, existing, value)
        if error:
            return _fail(
                code="payload_invalid",
                message=error,
                req_id=req_id,
                field=field,
                jsonpath="$.payload.value",
            )
        value = prepared_transition
    # Reach this amendment's in-flight admitted copies or refuse by name,
    # before either row is written.
    admitted_copies: tuple[int, ...] = ()
    if not existing["deployment_run_id"]:
        reached, refusal = reconcile_admitted_copies(
            conn, source_requirement_id=int(req_id), field=field, value=value
        )
        if refusal:
            return _fail(
                code=ADMITTED_COPY_IN_FLIGHT_CODE,
                message=refusal,
                req_id=req_id,
                field=field,
                jsonpath="$.payload.value",
            )
        admitted_copies = tuple(reached)
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
            conn,
            int(req_id),
            {"execution_target_json": target_json, "execution_target_digest": digest},
        )
        value = name
    else:
        conn.execute(
            f"UPDATE qa_requirements SET {field} = {marker} WHERE id = {marker}",
            (value, int(req_id)),
        )
    refusal = field in LINK_SCOPE_FIELDS and linked_scope_refusal(
        conn, (int(req_id), *admitted_copies), change=f"setting {field}"
    )
    if refusal:
        conn.rollback()
        return _fail(
            code=LINKED_SCOPE_CHANGE_CODE, message=refusal, req_id=req_id, field=field
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
        admitted_copies_updated=admitted_copies,
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
