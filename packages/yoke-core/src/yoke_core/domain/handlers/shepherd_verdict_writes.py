"""Shepherd verdict and caveat-disposition write handlers."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ShepherdVerdictRequest(BaseModel):
    transition: str = Field(..., min_length=1)
    worker: str = Field(..., min_length=1)
    verdict: str = Field(..., min_length=1)
    caveats: Optional[str] = None


class ShepherdVerdictResponse(BaseModel):
    item: str
    verdict_id: int


class ShepherdCaveatDispositionRequest(BaseModel):
    transition: str = Field(..., min_length=1)
    attempt: int
    caveat_num: int
    caveat_text: str = Field(..., min_length=1)
    disposition: str = Field(..., min_length=1)
    resolution_details: Optional[str] = None
    verdict_id: Optional[int] = None


class ShepherdCaveatDispositionResponse(BaseModel):
    item: str
    result: str


def _err(code: str, message: str, *, jsonpath: str | None = None) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _validate(model_cls, payload: Any, label: str):
    try:
        return model_cls.model_validate(payload or {}), None
    except Exception as exc:
        return None, _err("payload_invalid", f"{label} payload invalid: {exc}")


def _item_ref(request: FunctionCallRequest) -> tuple[str | None, HandlerOutcome | None]:
    item_id = request.target.item_id
    if request.target.kind != "item" or item_id is None:
        return None, _err(
            "target_invalid",
            "shepherd verdict writes require target.kind='item' with item_id",
            jsonpath="$.target.item_id",
        )
    return f"YOK-{int(item_id)}", None


def _run_with_conn(fn, *args, **kwargs) -> str:
    from yoke_core.domain import db_helpers

    conn = db_helpers.connect()
    try:
        return fn(conn, *args, **kwargs)
    finally:
        conn.close()


def _domain_error(exc: Exception) -> HandlerOutcome:
    code = "not_found" if isinstance(exc, LookupError) else "write_failed"
    return _err(code, str(exc))


def handle_shepherd_verdict(request: FunctionCallRequest) -> HandlerOutcome:
    body, err = _validate(ShepherdVerdictRequest, request.payload, "verdict")
    if err is not None:
        return err
    item, err = _item_ref(request)
    if err is not None:
        return err
    assert item is not None

    from yoke_core.domain.shepherd_verdict_log import cmd_verdict

    try:
        verdict_id = int(
            _run_with_conn(
                cmd_verdict,
                item,
                body.transition,
                body.worker,
                body.verdict,
                body.caveats,
            )
        )
    except (LookupError, ValueError, RuntimeError) as exc:
        return _domain_error(exc)
    return HandlerOutcome(
        result_payload={"item": item, "verdict_id": verdict_id},
        primary_success=True,
    )


def handle_shepherd_caveat_disposition(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    body, err = _validate(
        ShepherdCaveatDispositionRequest,
        request.payload,
        "caveat_disposition",
    )
    if err is not None:
        return err
    item, err = _item_ref(request)
    if err is not None:
        return err
    assert item is not None

    from yoke_core.domain.shepherd_verdict_log import cmd_caveat_disposition

    try:
        result = _run_with_conn(
            cmd_caveat_disposition,
            item,
            body.transition,
            int(body.attempt),
            int(body.caveat_num),
            body.caveat_text,
            body.disposition,
            body.resolution_details,
            body.verdict_id,
        )
    except (LookupError, ValueError, RuntimeError) as exc:
        return _domain_error(exc)
    return HandlerOutcome(
        result_payload={"item": item, "result": result},
        primary_success=True,
    )


__all__ = [
    "ShepherdVerdictRequest",
    "ShepherdVerdictResponse",
    "ShepherdCaveatDispositionRequest",
    "ShepherdCaveatDispositionResponse",
    "handle_shepherd_verdict",
    "handle_shepherd_caveat_disposition",
]
