"""Ouroboros entry/write lifecycle handlers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class OuroborosEntryInsertRequest(BaseModel):
    agent: str
    category: str
    observation: str
    context: Optional[str] = None
    timestamp: Optional[str] = None
    project: Optional[str] = None


class OuroborosEntryInsertResponse(BaseModel):
    entry_id: str


class OuroborosEntryIdRequest(BaseModel):
    entry_id: int


class OuroborosEntryLifecycleResponse(BaseModel):
    message: str


class OuroborosEntryArchiveRequest(BaseModel):
    entry_id: Optional[int] = None
    all_reviewed: bool = False


class OuroborosWrapupListRequest(BaseModel):
    pass


class OuroborosWrapupListResponse(BaseModel):
    rows: List[Dict[str, str]]


class OuroborosWrapupSaveRequest(BaseModel):
    session_timestamp: str
    body: str


class OuroborosWrapupSaveResponse(BaseModel):
    wrapup_id: int
    session_timestamp: str


def _bad_request(message: str, *, jsonpath: str = "$.payload") -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(
            code="payload_invalid",
            message=message,
            jsonpath=jsonpath,
        ),
    )


def handle_ouroboros_entry_insert(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        payload = OuroborosEntryInsertRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    if not payload.agent.strip():
        return _bad_request("agent must be non-empty", jsonpath="$.payload.agent")
    if not payload.category.strip():
        return _bad_request(
            "category must be non-empty", jsonpath="$.payload.category"
        )
    if not payload.observation.strip():
        return _bad_request(
            "observation must be non-empty", jsonpath="$.payload.observation"
        )
    from yoke_core.domain.db_helpers import connect, iso8601_now
    from yoke_core.domain.ouroboros_entries import cmd_insert_entry

    with connect() as conn:
        entry_id = cmd_insert_entry(
            conn,
            payload.timestamp or iso8601_now(),
            payload.agent,
            payload.context,
            payload.category,
            payload.observation,
            payload.project,
        )
    return HandlerOutcome(
        result_payload=OuroborosEntryInsertResponse(
            entry_id=entry_id,
        ).model_dump(),
        primary_success=True,
    )


def handle_ouroboros_entry_mark_reviewed(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        payload = OuroborosEntryIdRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.ouroboros_entries import cmd_mark_reviewed

    try:
        with connect() as conn:
            message = cmd_mark_reviewed(conn, payload.entry_id)
    except LookupError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(code="not_found", message=str(exc)),
        )
    return HandlerOutcome(
        result_payload=OuroborosEntryLifecycleResponse(
            message=message,
        ).model_dump(),
        primary_success=True,
    )


def handle_ouroboros_entry_mark_archived(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        payload = OuroborosEntryArchiveRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    if not payload.all_reviewed and payload.entry_id is None:
        return _bad_request("entry_id is required unless all_reviewed=true")
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.ouroboros_entries import cmd_mark_archived

    try:
        with connect() as conn:
            message = cmd_mark_archived(
                conn,
                entry_id=payload.entry_id,
                all_reviewed=payload.all_reviewed,
            )
    except LookupError as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(code="not_found", message=str(exc)),
        )
    except ValueError as exc:
        return _bad_request(str(exc))
    return HandlerOutcome(
        result_payload=OuroborosEntryLifecycleResponse(
            message=message,
        ).model_dump(),
        primary_success=True,
    )


def handle_ouroboros_wrapup_list(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        OuroborosWrapupListRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.ouroboros_wrapups import cmd_list_wrapups

    with connect() as conn:
        text = cmd_list_wrapups(conn)
    rows: List[Dict[str, str]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("|")
        rows.append(
            {
                "id": parts[0] if len(parts) > 0 else "",
                "session_timestamp": parts[1] if len(parts) > 1 else "",
                "created_at": parts[2] if len(parts) > 2 else "",
            }
        )
    return HandlerOutcome(
        result_payload=OuroborosWrapupListResponse(rows=rows).model_dump(),
        primary_success=True,
    )


def handle_ouroboros_wrapup_save(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        payload = OuroborosWrapupSaveRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    if not payload.session_timestamp.strip():
        return _bad_request(
            "session_timestamp must be non-empty",
            jsonpath="$.payload.session_timestamp",
        )
    if not payload.body.strip():
        return _bad_request("body must be non-empty", jsonpath="$.payload.body")
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.ouroboros_wrapups import cmd_insert_wrapup

    with connect() as conn:
        wrapup_id = cmd_insert_wrapup(
            conn, payload.session_timestamp.strip(), payload.body,
        )
    return HandlerOutcome(
        result_payload=OuroborosWrapupSaveResponse(
            wrapup_id=int(wrapup_id),
            session_timestamp=payload.session_timestamp.strip(),
        ).model_dump(),
        primary_success=True,
    )


REGISTRATIONS: List[Dict[str, Any]] = [
    {
        "function_id": "ouroboros.entry.insert",
        "handler": handle_ouroboros_entry_insert,
        "request_model": OuroborosEntryInsertRequest,
        "response_model": OuroborosEntryInsertResponse,
        "side_effects": ["db_write"],
    },
    {
        "function_id": "ouroboros.entry.mark_reviewed",
        "handler": handle_ouroboros_entry_mark_reviewed,
        "request_model": OuroborosEntryIdRequest,
        "response_model": OuroborosEntryLifecycleResponse,
        "side_effects": ["db_write"],
    },
    {
        "function_id": "ouroboros.entry.mark_archived",
        "handler": handle_ouroboros_entry_mark_archived,
        "request_model": OuroborosEntryArchiveRequest,
        "response_model": OuroborosEntryLifecycleResponse,
        "side_effects": ["db_write"],
    },
    {
        "function_id": "ouroboros.wrapup.list",
        "handler": handle_ouroboros_wrapup_list,
        "request_model": OuroborosWrapupListRequest,
        "response_model": OuroborosWrapupListResponse,
        "side_effects": [],
    },
    {
        "function_id": "ouroboros.wrapup.save",
        "handler": handle_ouroboros_wrapup_save,
        "request_model": OuroborosWrapupSaveRequest,
        "response_model": OuroborosWrapupSaveResponse,
        "side_effects": ["wrapup_reports_write"],
    },
]

for entry in REGISTRATIONS:
    entry.update(
        {
            "stability": "stable",
            "owner_module": "yoke_core.domain.handlers.ouroboros_writes",
            "target_kinds": ["global"],
            "emitted_event_names": ["YokeFunctionCalled"],
            "guardrails": [],
            "adapter_status": "live",
            "claim_required_kind": None,
            "ambient_session_required": False,
        }
    )


__all__ = [
    "REGISTRATIONS",
    "handle_ouroboros_entry_insert",
    "handle_ouroboros_entry_mark_reviewed",
    "handle_ouroboros_entry_mark_archived",
    "handle_ouroboros_wrapup_list",
    "handle_ouroboros_wrapup_save",
]
