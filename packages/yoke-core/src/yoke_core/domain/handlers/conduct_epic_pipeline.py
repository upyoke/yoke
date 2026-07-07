"""Conduct-owned epic pipeline wrappers.

These function ids cover operations whose semantics are larger than a
plain epic table update: the full task status pipeline and the
PROCEED-triage reviewed handoff path.
"""

from __future__ import annotations

import contextlib
import io
import os
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from yoke_core.domain import epic, update_status
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


_OWNER = "yoke_core.domain.handlers.conduct_epic_pipeline"


class PipelineUpdateStatusRequest(BaseModel):
    status: str = Field(..., min_length=1)
    note: str = ""
    no_rebuild: bool = False
    no_github: bool = False
    no_derive: bool = False
    claim_bypass: str = ""
    status_source: str = "conduct"


class PipelineUpdateStatusResponse(BaseModel):
    epic_id: int
    task_num: int
    status: str
    stdout: str
    stderr: str


class ProceedTriageHandoffRequest(BaseModel):
    recommendation: str = "PROCEED"
    gap_summary: str = ""
    filed_ticket_ids: List[str] = Field(default_factory=list)
    session_id: Optional[str] = None


class ProceedTriageHandoffResponse(BaseModel):
    epic_id: int
    stdout: str
    stderr: str


def _bad(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={}, primary_success=False,
        error=FunctionError(code="invalid_payload", message=message),
    )


def _failure(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={}, primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _open_connection():
    from yoke_core.domain import db_helpers
    return db_helpers.connect()


def _task_target(request: FunctionCallRequest) -> Optional[Tuple[int, int]]:
    target = request.target
    if (
        target.kind != "epic_task"
        or target.epic_id is None
        or target.task_num is None
    ):
        return None
    return int(target.epic_id), int(target.task_num)


def _epic_id(request: FunctionCallRequest) -> Optional[int]:
    target = request.target
    if target.kind != "epic_task" or target.epic_id is None:
        return None
    return int(target.epic_id)


@contextlib.contextmanager
def _temporary_env(updates: Dict[str, str]):
    old = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value:
                os.environ[key] = value
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def handle_update_status(request: FunctionCallRequest) -> HandlerOutcome:
    ids = _task_target(request)
    if ids is None:
        return _bad("target must carry epic_id + task_num")
    try:
        payload = PipelineUpdateStatusRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad(f"payload invalid: {exc}")
    epic_id, task_num = ids
    stdout = io.StringIO()
    stderr = io.StringIO()
    env = {"YOKE_STATUS_SOURCE": payload.status_source}
    if payload.claim_bypass:
        env["YOKE_CLAIM_BYPASS"] = payload.claim_bypass
    with _open_connection() as conn, _temporary_env(env):
        try:
            rc = update_status.update_task_status(
                conn, str(epic_id), str(task_num), payload.status, payload.note,
                no_rebuild=payload.no_rebuild,
                no_github=payload.no_github,
                no_derive=payload.no_derive,
                stdout=stdout,
                stderr=stderr,
            )
        except SystemExit as exc:
            rc = int(exc.code or 0)
    result = PipelineUpdateStatusResponse(
        epic_id=epic_id, task_num=task_num, status=payload.status,
        stdout=stdout.getvalue(), stderr=stderr.getvalue(),
    )
    if rc != 0:
        return _failure(
            "status_pipeline_failed",
            result.stderr.strip() or result.stdout.strip()
            or f"status pipeline exited {rc}",
        )
    return HandlerOutcome(result_payload=result.model_dump(), primary_success=True)


def handle_proceed_triage_handoff(request: FunctionCallRequest) -> HandlerOutcome:
    epic_id = _epic_id(request)
    if epic_id is None:
        return _bad("target must carry epic_id")
    try:
        payload = ProceedTriageHandoffRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad(f"payload invalid: {exc}")
    stdout = io.StringIO()
    stderr = io.StringIO()
    session_id = payload.session_id or request.actor.session_id
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        rc = epic.proceed_triage_and_handoff(
            epic_id,
            recommendation=payload.recommendation,
            gap_summary=payload.gap_summary,
            filed_ticket_ids=payload.filed_ticket_ids,
            session_id=session_id,
        )
    result = ProceedTriageHandoffResponse(
        epic_id=epic_id, stdout=stdout.getvalue(), stderr=stderr.getvalue(),
    )
    if rc != 0:
        return _failure(
            "proceed_triage_handoff_failed",
            result.stderr.strip() or result.stdout.strip()
            or f"proceed triage handoff exited {rc}",
        )
    return HandlerOutcome(result_payload=result.model_dump(), primary_success=True)


def _entry(fid: str, handler: Any, req: Any, resp: Any, effects: List[str],
           claim: Optional[str]) -> Dict[str, Any]:
    return {
        "function_id": fid,
        "handler": handler,
        "request_model": req,
        "response_model": resp,
        "stability": "stable",
        "owner_module": _OWNER,
        "target_kinds": ["epic_task"],
        "side_effects": effects,
        "emitted_event_names": ["YokeFunctionCalled"],
        "guardrails": [],
        "adapter_status": "live",
        "claim_required_kind": claim,
    }


REGISTRATIONS: List[Dict[str, Any]] = [
    _entry("conduct.epic_task.update_status", handle_update_status,
           PipelineUpdateStatusRequest, PipelineUpdateStatusResponse,
           ["epic_task_status_pipeline", "github_sync", "rebuild_board"],
           None),
    _entry("conduct.epic.proceed_triage_handoff",
           handle_proceed_triage_handoff,
           ProceedTriageHandoffRequest, ProceedTriageHandoffResponse,
           ["qa_runs_insert", "epic_status_handoff", "claim_release"],
           "epic"),
]


__all__ = ["REGISTRATIONS", "handle_update_status",
           "handle_proceed_triage_handoff"]
