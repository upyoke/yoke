"""Internal server-side status flips for the done-transition path.

The done transition flips ``item -> done`` and cascades ``epic-task -> done``
while BYPASSING the work-claim. That bypass used to travel on process-global
environment variables set inside the engine, which is unsafe over an https
control plane that relays many requests through one process. These handlers
carry the bypass on a request-scoped ContextVar
(:mod:`yoke_core.domain.status_claim_bypass_context`) posted around the
UNCHANGED domain write, so the claim-verification sites read it per request
with no cross-request leak.

Each handler is a thin wrapper: the item flip runs the unchanged
:func:`yoke_core.domain.backlog.execute_update`; the epic-task flip runs the
unchanged :func:`yoke_core.domain.update_status.update_task_status`. The engine
keeps its operator narratives and retry logic; these handlers only apply the
write server-side and return the caller-facing result.

Both are ``adapter_status='internal'`` (merge finalize glue, never an agent CLI
surface) and ``ambient_session_required=False`` (the done transition runs in a
merge subprocess that may resolve no ambient harness session). They are
``claim_required_kind=None`` BY DESIGN — the done ceremony intentionally
bypasses the item claim — but are authorization-gated ``PROJECT`` +
``PERM_ITEMS_WRITE`` (see ``function_authz_product_scopes``) so an unauthorized
caller can never reach the bypass.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.status_claim_bypass_context import status_bypass_override


class ItemStatusSetRequest(BaseModel):
    field: str = Field(..., min_length=1)
    value: str = Field(..., min_length=1)
    claim_bypass: str = ""
    status_source: str = ""
    qa_bypass: Optional[bool] = None
    done_nonce_verified: bool = False
    no_github: bool = False
    rebuild_board: bool = False


class ItemStatusSetResponse(BaseModel):
    applied: bool
    status_write_success: bool
    status_write_error: str = ""
    status_write_error_code: str = ""


class EpicTaskStatusSetRequest(BaseModel):
    epic_id: str = Field(..., min_length=1)
    task_num: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    note: str = ""
    claim_bypass: str = ""
    status_source: str = ""
    task_done_verified: bool = False
    no_rebuild: bool = True
    no_github: bool = True
    no_derive: bool = True


class EpicTaskStatusSetResponse(BaseModel):
    rc: int


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _require_item_id(request: FunctionCallRequest) -> Optional[int]:
    if request.target.item_id is None:
        return None
    return int(request.target.item_id)


def handle_item_status_set(request: FunctionCallRequest) -> HandlerOutcome:
    """Flip an item status field with the claim check request-scoped-bypassed.

    Posts the ``(claim_bypass, status_source)`` override on the request-scoped
    ContextVar around the UNCHANGED :func:`backlog.execute_update`. The
    ``done_nonce_verified`` / ``qa_bypass`` typed guards and ``no_github`` /
    ``rebuild_board`` flags are threaded exactly as the engine's direct write
    did. ``primary_success`` mirrors the former direct applier's return-code
    contract: True whenever ``execute_update`` returns (even on an inner gate
    failure), and only False on a genuine write exception.

    A refused inner gate therefore travels in the result payload rather than
    as a transport error, and the refusal TEXT travels with it: the engine
    that reads this runs client-side over an https relay, where the gate's own
    narrative goes to server stdout and is lost. Without it the caller can see
    that the status did not move but cannot say why.
    """
    import sys

    item_id = _require_item_id(request)
    if item_id is None:
        return _err("target_invalid", "item_status_set requires target.item_id")
    try:
        body = ItemStatusSetRequest.model_validate(request.payload)
    except ValidationError as exc:
        return _err("payload_invalid", f"item_status_set payload invalid: {exc}")

    from yoke_core.domain import backlog

    kwargs: dict = {
        "out": sys.stdout,
        "session_id": request.actor.session_id or None,
    }
    if body.done_nonce_verified:
        kwargs["done_nonce_verified"] = True
    if body.qa_bypass is not None:
        kwargs["qa_bypass"] = body.qa_bypass
    try:
        with status_bypass_override(
            claim_bypass=body.claim_bypass,
            status_source=body.status_source,
            task_done_verified=False,
        ):
            result = backlog.execute_update(
                item_id,
                body.field,
                body.value,
                rebuild_board=body.rebuild_board,
                no_github=body.no_github,
                **kwargs,
            )
    except Exception as exc:  # noqa: BLE001 - engine treated a raise as failure
        return _err("item_status_set_failed", str(exc))

    return HandlerOutcome(
        result_payload={
            "applied": True,
            "status_write_success": bool(result.get("success", False)),
            "status_write_error": str(result.get("error") or ""),
            "status_write_error_code": str(result.get("error_code") or ""),
        },
        primary_success=True,
    )


def handle_epic_task_status_set(request: FunctionCallRequest) -> HandlerOutcome:
    """Flip an epic-task status with the claim + done guards request-scoped.

    Posts the ``(claim_bypass, status_source, task_done_verified)`` override on
    the request-scoped ContextVar around the UNCHANGED
    :func:`update_status.update_task_status`, returning its int rc. A genuine
    write exception surfaces as a structured error so the engine's cascade
    aborts exactly as the former direct call's propagating exception did.
    """
    import sys

    try:
        body = EpicTaskStatusSetRequest.model_validate(request.payload)
    except ValidationError as exc:
        return _err("payload_invalid", f"epic_task_status_set payload invalid: {exc}")

    from yoke_core.domain import db_helpers
    from yoke_core.domain.update_status import update_task_status

    try:
        with status_bypass_override(
            claim_bypass=body.claim_bypass,
            status_source=body.status_source,
            task_done_verified=body.task_done_verified,
        ):
            with db_helpers.connect() as conn:
                rc = update_task_status(
                    conn,
                    body.epic_id,
                    body.task_num,
                    body.status,
                    note=body.note,
                    no_rebuild=body.no_rebuild,
                    no_github=body.no_github,
                    no_derive=body.no_derive,
                    stdout=sys.stdout,
                    stderr=sys.stderr,
                )
    except Exception as exc:  # noqa: BLE001 - surfaced so the cascade aborts
        return _err("epic_task_status_set_failed", str(exc))

    return HandlerOutcome(
        result_payload={"rc": int(rc)},
        primary_success=True,
    )


__all__ = [
    "ItemStatusSetRequest",
    "ItemStatusSetResponse",
    "EpicTaskStatusSetRequest",
    "EpicTaskStatusSetResponse",
    "handle_item_status_set",
    "handle_epic_task_status_set",
]
