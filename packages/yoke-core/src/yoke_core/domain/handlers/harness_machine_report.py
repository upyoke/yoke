"""Server-side persist for client-collected harness machine reports."""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class HarnessMachineReportRow(BaseModel):
    harness_id: str
    glue_written: bool = False
    glue_present: bool = False
    glue_malformed: bool = False
    config_present: bool = False
    project_entry_present: bool = False
    approval_state: str = "unknown"


class HarnessMachineReportUpsertRequest(BaseModel):
    project_id: int
    reports: List[HarnessMachineReportRow] = Field(default_factory=list)
    pack_prerequisites: List[Dict[str, Any]] = Field(default_factory=list)


class HarnessMachineReportUpsertResponse(BaseModel):
    project_id: int
    reports: List[Dict[str, Any]]
    pack_prerequisites: List[Dict[str, Any]]


def handle_harness_machine_report_upsert(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    if request.target.kind != "global":
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="target_invalid",
                message="harness.machine_report.upsert requires target.kind='global'",
                jsonpath="$.target.kind",
            ),
        )
    try:
        parsed = HarnessMachineReportUpsertRequest.model_validate(
            request.payload or {},
        )
    except ValueError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=str(exc),
                jsonpath="$.payload",
            ),
        )
    from yoke_core.domain import db_helpers
    from yoke_core.domain.harness_machine_state import (
        upsert_harness_machine_reports,
    )

    conn = db_helpers.connect()
    try:
        stored = upsert_harness_machine_reports(
            conn,
            project_id=parsed.project_id,
            reports=[row.model_dump() for row in parsed.reports],
        )
    except ValueError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(code="payload_invalid", message=str(exc)),
        )
    finally:
        conn.close()
    return HandlerOutcome(
        primary_success=True,
        result_payload={
            "project_id": parsed.project_id,
            "reports": stored,
            "pack_prerequisites": parsed.pack_prerequisites,
        },
    )


__all__ = [
    "HarnessMachineReportUpsertRequest",
    "HarnessMachineReportUpsertResponse",
    "handle_harness_machine_report_upsert",
]
