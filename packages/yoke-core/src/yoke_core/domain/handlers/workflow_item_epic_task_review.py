"""Handlers for the ``workflow_item.epic_task.review_*`` function family.

Four function ids covering the tester-subagent review hot path:

- ``workflow_item.epic_task.review_seed`` — idempotently seed the
  blocking implementation-review requirement (auto-advances
  ``implementing -> reviewing-implementation``).
- ``workflow_item.epic_task.review_insert`` — record a pass/fail
  verdict (auto-advances ``reviewing-implementation ->
  reviewed-implementation`` on pass).
- ``workflow_item.epic_task.review_get`` — most recent review row.
- ``workflow_item.epic_task.review_list`` — review history rows.

Each handler is a thin typed wrapper around the existing domain owners
on :mod:`yoke_core.domain.epic` (``review_seed`` / ``review_insert``
/ ``review_get`` / ``review_list``) — business rules (requirement
reuse, verdict-driven auto-transitions, qa-run insertion) live there.
Read rows keep the pipe-delimited format
``id|epic_id|task_num|verdict|body|created_at`` so output parses the
same as the retained ``db_router epic review-get`` operator fallback.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

from yoke_core.domain import epic
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


_OWNER_MODULE = "yoke_core.domain.handlers.workflow_item_epic_task_review"


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ReviewSeedRequest(BaseModel):
    """No payload — the target carries ``(epic_id, task_num)``."""


class ReviewSeedResponse(BaseModel):
    epic_id: int
    task_num: int
    message: str


class ReviewInsertRequest(BaseModel):
    verdict: str
    body: str

    @field_validator("verdict")
    @classmethod
    def _normalize_verdict(cls, value: str) -> str:
        lowered = (value or "").strip().lower()
        if lowered not in ("pass", "fail"):
            raise ValueError("verdict must be 'pass' or 'fail'")
        return lowered


class ReviewInsertResponse(BaseModel):
    epic_id: int
    task_num: int
    verdict: str
    message: str


class ReviewGetRequest(BaseModel):
    """No payload — the target carries ``(epic_id, task_num)``."""


class ReviewGetResponse(BaseModel):
    epic_id: int
    task_num: int
    review: str


class ReviewListRequest(BaseModel):
    limit: int = Field(0, ge=0)


class ReviewListResponse(BaseModel):
    epic_id: int
    task_num: int
    reviews: str
    count: int


# ---------------------------------------------------------------------------
# Shared helpers (per-module by convention: tests patch
# ``<module>._open_connection`` per handler module)
# ---------------------------------------------------------------------------


def _bad_request(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={}, primary_success=False,
        error=FunctionError(code="invalid_payload", message=message),
    )


def _not_found(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={}, primary_success=False,
        error=FunctionError(code="target_not_found", message=message),
    )


def _downstream_failure(message: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={}, primary_success=False,
        error=FunctionError(code="downstream_failure", message=message),
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


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def handle_review_seed(request: FunctionCallRequest) -> HandlerOutcome:
    """Seed the implementation-review requirement via ``epic.review_seed``."""
    ids = _task_target(request)
    if ids is None:
        return _bad_request("target must carry epic_id + task_num")
    epic_id, task_num = ids
    try:
        ReviewSeedRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    with _open_connection() as conn:
        try:
            message = epic.review_seed(conn, str(epic_id), task_num)
        except LookupError as exc:
            return _not_found(str(exc))
        except RuntimeError as exc:
            return _downstream_failure(str(exc))
    response = ReviewSeedResponse(
        epic_id=epic_id, task_num=task_num, message=message,
    )
    return HandlerOutcome(result_payload=response.model_dump(), primary_success=True)


def handle_review_insert(request: FunctionCallRequest) -> HandlerOutcome:
    """Record a review verdict via ``epic.review_insert``."""
    ids = _task_target(request)
    if ids is None:
        return _bad_request("target must carry epic_id + task_num")
    epic_id, task_num = ids
    try:
        payload = ReviewInsertRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    with _open_connection() as conn:
        try:
            message = epic.review_insert(
                conn, str(epic_id), task_num, payload.verdict, payload.body,
            )
        except LookupError as exc:
            return _not_found(str(exc))
        except RuntimeError as exc:
            return _downstream_failure(str(exc))
    response = ReviewInsertResponse(
        epic_id=epic_id, task_num=task_num,
        verdict=payload.verdict, message=message,
    )
    return HandlerOutcome(result_payload=response.model_dump(), primary_success=True)


def handle_review_get(request: FunctionCallRequest) -> HandlerOutcome:
    """Read the most recent review via ``epic.review_get``."""
    ids = _task_target(request)
    if ids is None:
        return _bad_request("target must carry epic_id + task_num")
    epic_id, task_num = ids
    try:
        ReviewGetRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    with _open_connection() as conn:
        try:
            review = epic.review_get(conn, str(epic_id), task_num)
        except LookupError as exc:
            return _not_found(str(exc))
    response = ReviewGetResponse(
        epic_id=epic_id, task_num=task_num, review=review,
    )
    return HandlerOutcome(result_payload=response.model_dump(), primary_success=True)


def handle_review_list(request: FunctionCallRequest) -> HandlerOutcome:
    """List review history via ``epic.review_list`` (empty list is not an error).

    ``count`` counts review ROWS (the domain returns one string per
    row); review bodies are multi-line, so line-counting the joined
    text would over-count.
    """
    ids = _task_target(request)
    if ids is None:
        return _bad_request("target must carry epic_id + task_num")
    epic_id, task_num = ids
    try:
        payload = ReviewListRequest.model_validate(request.payload)
    except Exception as exc:
        return _bad_request(f"payload invalid: {exc}")
    with _open_connection() as conn:
        rows = epic.review_list(conn, str(epic_id), task_num, payload.limit)
    response = ReviewListResponse(
        epic_id=epic_id, task_num=task_num,
        reviews="\n".join(rows), count=len(rows),
    )
    return HandlerOutcome(result_payload=response.model_dump(), primary_success=True)


# ---------------------------------------------------------------------------
# Registration descriptors
# ---------------------------------------------------------------------------


def _kwargs(
    fid: str, h: Any, req: Any, resp: Any,
    side_effects: List[str], claim: Optional[str],
) -> Dict[str, Any]:
    return {
        "function_id": fid, "handler": h,
        "request_model": req, "response_model": resp,
        "stability": "stable",
        "owner_module": _OWNER_MODULE,
        "target_kinds": ["epic_task"],
        "side_effects": side_effects,
        "emitted_event_names": ["YokeFunctionCalled"],
        "guardrails": [],
        "adapter_status": "live",
        "claim_required_kind": claim,
    }


REGISTRATIONS: List[Dict[str, Any]] = [
    _kwargs(
        "workflow_item.epic_task.review_seed", handle_review_seed,
        ReviewSeedRequest, ReviewSeedResponse,
        ["qa_requirements_insert", "epic_tasks_status_update"], "epic",
    ),
    _kwargs(
        "workflow_item.epic_task.review_insert", handle_review_insert,
        ReviewInsertRequest, ReviewInsertResponse,
        ["qa_runs_insert", "epic_tasks_status_update"], "epic",
    ),
    _kwargs(
        "workflow_item.epic_task.review_get", handle_review_get,
        ReviewGetRequest, ReviewGetResponse, [], None,
    ),
    _kwargs(
        "workflow_item.epic_task.review_list", handle_review_list,
        ReviewListRequest, ReviewListResponse, [], None,
    ),
]


__all__ = [
    "handle_review_seed", "handle_review_insert",
    "handle_review_get", "handle_review_list",
    "ReviewSeedRequest", "ReviewSeedResponse",
    "ReviewInsertRequest", "ReviewInsertResponse",
    "ReviewGetRequest", "ReviewGetResponse",
    "ReviewListRequest", "ReviewListResponse",
    "REGISTRATIONS",
]
