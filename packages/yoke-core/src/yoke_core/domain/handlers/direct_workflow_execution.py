"""Registered survey, evidence, and escalation writes for direct workflows."""

from __future__ import annotations

import io
from typing import Any, List, Mapping, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.dash_execution import (
    DASH_ESCALATION_SECTION,
    record_dash_escalation,
    record_dash_evidence,
)
from yoke_core.domain.item_json_sections import read_json_section
from yoke_core.domain.handlers.direct_workflow_survey import (
    SurveyRequest,
    SurveyResponse,
    handle_survey,
)


class EvidenceRequest(BaseModel):
    result_summary: str
    verification_summary: str
    verification_status: str = "passed"
    commit_sha: str = ""
    merge_sha: str = ""
    touched_files: List[str] = Field(default_factory=list)
    posture_checks: Mapping[str, str] = Field(default_factory=dict)
    no_changes: bool = False
    # Which tree the verification summary describes. Resolved by the
    # caller, because only the machine holding the checkout can answer.
    tree_root: str = ""
    tree_head_sha: str = ""


class EvidenceResponse(BaseModel):
    item_id: int
    recorded: bool
    evidence: dict[str, Any]


class EscalateRequest(BaseModel):
    issue_title: str = Field(..., min_length=1, max_length=100)
    findings: str = Field(..., min_length=1)
    priority: Optional[str] = None


class EscalateResponse(BaseModel):
    item_id: int
    issue_item_id: int
    issue_ref: str
    cancelled: bool
    existing: bool = False


def _error(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _item_id(
    request: FunctionCallRequest,
) -> tuple[Optional[int], Optional[HandlerOutcome]]:
    if request.target.kind != "item" or request.target.item_id is None:
        return None, _error(
            "invalid_target",
            "target must carry kind='item' and item_id",
        )
    return int(request.target.item_id), None


def _actor_id(request: FunctionCallRequest) -> Optional[str]:
    value = request.actor.actor_id
    return str(value) if value is not None and str(value).isdigit() else None


def handle_dash_survey(request: FunctionCallRequest) -> HandlerOutcome:
    return handle_survey(request, expected_workflow="dash")


def handle_blitz_survey(request: FunctionCallRequest) -> HandlerOutcome:
    return handle_survey(request, expected_workflow="blitz")


def handle_dash_evidence(request: FunctionCallRequest) -> HandlerOutcome:
    item_id, invalid = _item_id(request)
    if invalid:
        return invalid
    try:
        payload = EvidenceRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("invalid_payload", f"payload invalid: {exc}")
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        try:
            evidence = record_dash_evidence(
                conn,
                item_id=item_id,
                result_summary=payload.result_summary,
                verification_summary=payload.verification_summary,
                verification_status=payload.verification_status,
                commit_sha=payload.commit_sha,
                merge_sha=payload.merge_sha,
                touched_files=payload.touched_files,
                tree_root=payload.tree_root,
                tree_head_sha=payload.tree_head_sha,
                posture_checks=payload.posture_checks,
                no_changes=payload.no_changes,
                actor_id=_actor_id(request) or "",
            )
        except (LookupError, ValueError) as exc:
            return _error("evidence_refused", str(exc))
    return HandlerOutcome(
        result_payload=EvidenceResponse(
            item_id=item_id,
            recorded=True,
            evidence=evidence,
        ).model_dump(),
    )


def _dash_project(conn: Any, item_id: int) -> tuple[str, int]:
    row = conn.execute(
        "SELECT p.slug, i.project_id FROM items i "
        "JOIN projects p ON p.id = i.project_id "
        "WHERE i.id = %s AND i.workflow_id = 'dash'",
        (item_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"item {item_id} is not a Dash")
    return str(row[0]), int(row[1])


def _cancel_dash(item_id: int, session_id: Optional[str]) -> tuple[bool, str]:
    from yoke_core.domain import backlog

    captured = io.StringIO()
    result = backlog.execute_update(
        item_id=item_id,
        field="status",
        value="cancelled",
        session_id=session_id,
        out=captured,
    )
    return bool(result.get("success")), str(
        result.get("error") or captured.getvalue(),
    )


def handle_dash_escalate(request: FunctionCallRequest) -> HandlerOutcome:
    """Create one absorbing Issue, link it, then cancel the Dash."""
    item_id, invalid = _item_id(request)
    if invalid:
        return invalid
    try:
        payload = EscalateRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("invalid_payload", f"payload invalid: {exc}")
    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        try:
            project_slug, _project_id = _dash_project(conn, item_id)
        except ValueError as exc:
            return _error("workflow_mismatch", str(exc))
        existing = read_json_section(
            conn,
            item_id=item_id,
            section=DASH_ESCALATION_SECTION,
        )
    if existing and existing.get("issue_item_id"):
        cancelled, reason = _cancel_dash(item_id, request.actor.session_id)
        if not cancelled:
            return _error("cancel_failed", reason)
        return HandlerOutcome(
            result_payload=EscalateResponse(
                item_id=item_id,
                issue_item_id=int(existing["issue_item_id"]),
                issue_ref=str(existing.get("issue_ref") or ""),
                cancelled=True,
                existing=True,
            ).model_dump(),
        )

    from yoke_core.domain.backlog_create_op import execute_create

    created = execute_create(
        title=payload.issue_title,
        workflow="issue",
        priority=payload.priority,
        project=project_slug,
        source=_actor_id(request),
        session_id=request.actor.session_id,
        entry_surface="harness_skill",
        instruction=payload.findings,
        out=io.StringIO(),
    )
    if not created.get("success"):
        return _error(
            "issue_create_failed",
            str(created.get("error") or "Issue creation failed"),
        )
    issue_item_id = int(created["item_id"])
    issue_ref = str(created.get("public_ref") or issue_item_id)
    with connect() as conn:
        record_dash_escalation(
            conn,
            item_id=item_id,
            findings=payload.findings,
            issue_item_id=issue_item_id,
            issue_ref=issue_ref,
        )
    cancelled, reason = _cancel_dash(item_id, request.actor.session_id)
    if not cancelled:
        return _error(
            "cancel_failed",
            f"Created {issue_ref} and recorded the link, but Dash "
            f"cancellation failed: {reason}",
        )
    return HandlerOutcome(
        result_payload=EscalateResponse(
            item_id=item_id,
            issue_item_id=issue_item_id,
            issue_ref=issue_ref,
            cancelled=True,
        ).model_dump(),
    )


REGISTRATIONS: list[dict[str, Any]] = [
    {
        "function_id": "direct_workflow.dash.survey",
        "handler": handle_dash_survey,
        "request_model": SurveyRequest,
        "response_model": SurveyResponse,
    },
    {
        "function_id": "direct_workflow.blitz.survey",
        "handler": handle_blitz_survey,
        "request_model": SurveyRequest,
        "response_model": SurveyResponse,
    },
    {
        "function_id": "direct_workflow.dash.evidence",
        "handler": handle_dash_evidence,
        "request_model": EvidenceRequest,
        "response_model": EvidenceResponse,
    },
    {
        "function_id": "direct_workflow.dash.escalate",
        "handler": handle_dash_escalate,
        "request_model": EscalateRequest,
        "response_model": EscalateResponse,
    },
]
_SIDE_EFFECTS = {
    "direct_workflow.dash.escalate": ["item_insert", "db_write", "github_sync"],
}
for _entry in REGISTRATIONS:
    _entry.update(
        {
            "stability": "stable",
            "owner_module": ("yoke_core.domain.handlers.direct_workflow_execution"),
            "target_kinds": ["item"],
            "side_effects": _SIDE_EFFECTS.get(_entry["function_id"], ["db_write"]),
            "emitted_event_names": ["YokeFunctionCalled"],
            "guardrails": ["direct_workflow_only"],
            "adapter_status": "live",
            "claim_required_kind": (
                None if _entry["function_id"].endswith(".survey") else "item"
            ),
        }
    )


__all__ = [
    "EvidenceRequest",
    "EvidenceResponse",
    "EscalateRequest",
    "EscalateResponse",
    "REGISTRATIONS",
    "SurveyRequest",
    "SurveyResponse",
    "handle_blitz_survey",
    "handle_dash_escalate",
    "handle_dash_evidence",
    "handle_dash_survey",
]
