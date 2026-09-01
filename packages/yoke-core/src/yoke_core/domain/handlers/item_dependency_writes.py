"""Item-dependency write handlers.

Wraps the dependency graph domain commands behind registered
function ids:

* ``items.dependency.add``
* ``items.dependency.update``
* ``items.dependency.remove``

The dependent item is the dispatcher target. The blocking item remains a
payload ref accepted by the underlying item-dependency domain owner.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ItemDependencyAddRequest(BaseModel):
    blocking_item: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)
    gate_point: str = "activation"
    satisfaction: Optional[str] = None
    rationale: str = Field(..., min_length=1)
    evidence_json: str = "{}"


class ItemDependencyAddResponse(BaseModel):
    dependent_item: str
    blocking_item: str
    gate_point: str
    satisfaction: Optional[str] = None
    source: str
    result: str


class ItemDependencyUpdateRequest(BaseModel):
    blocking_item: str = Field(..., min_length=1)
    match_gate_point: Optional[str] = None
    gate_point: Optional[str] = None
    satisfaction: Optional[str] = None
    rationale: Optional[str] = None


class ItemDependencyUpdateResponse(BaseModel):
    dependent_item: str
    blocking_item: str
    result: str


class ItemDependencyRemoveRequest(BaseModel):
    blocking_item: str = Field(..., min_length=1)


class ItemDependencyRemoveResponse(BaseModel):
    dependent_item: str
    blocking_item: str
    result: str


def _err(code: str, message: str, *, jsonpath: str | None = None) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _validate(model_cls, payload: Any, label: str):
    try:
        return model_cls.model_validate(payload), None
    except Exception as exc:
        return None, _err("payload_invalid", f"{label} payload invalid: {exc}")


def _dependent_item(request: FunctionCallRequest) -> tuple[str | None, HandlerOutcome | None]:
    """The dispatcher target rendered as the public PREFIX-N API token.

    ``target.item_id`` is the internal ``items.id``. Storage keeps that
    id; the handler result still names the item by its own project's
    prefix + project sequence.
    """
    item_id = request.target.item_id
    if request.target.kind != "item" or item_id is None:
        return None, _err(
            "target_invalid",
            "item dependency writes require target.kind='item' with item_id",
            jsonpath="$.target.item_id",
        )
    from yoke_core.domain.item_ref_columns import render_column_item_ref

    return _run_with_conn(render_column_item_ref, int(item_id)), None


def _run_with_conn(fn, *args, **kwargs) -> str:
    from yoke_core.domain import db_helpers

    conn = db_helpers.connect()
    try:
        return fn(conn, *args, **kwargs)
    finally:
        conn.close()


def _domain_error(exc: Exception) -> HandlerOutcome:
    code = "dependency_not_found" if isinstance(exc, LookupError) else "dependency_failed"
    return _err(code, str(exc))


def handle_item_dependency_add(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    body, err = _validate(
        ItemDependencyAddRequest, request.payload, "dependency_add",
    )
    if err is not None:
        return err
    dependent, err = _dependent_item(request)
    if err is not None:
        return err
    assert dependent is not None

    from yoke_core.domain.item_dependency import cmd_dependency_add

    try:
        result = _run_with_conn(
            cmd_dependency_add,
            dependent,
            body.blocking_item,
            body.source,
            gate_point=body.gate_point,
            satisfaction=body.satisfaction,
            rationale=body.rationale,
            evidence_json=body.evidence_json,
        )
    except (LookupError, ValueError, RuntimeError) as exc:
        return _domain_error(exc)
    return HandlerOutcome(
        result_payload={
            "dependent_item": dependent,
            "blocking_item": body.blocking_item,
            "gate_point": body.gate_point,
            "satisfaction": body.satisfaction,
            "source": body.source,
            "result": result,
        },
        primary_success=True,
    )


def handle_item_dependency_update(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    body, err = _validate(
        ItemDependencyUpdateRequest, request.payload, "dependency_update",
    )
    if err is not None:
        return err
    dependent, err = _dependent_item(request)
    if err is not None:
        return err
    assert dependent is not None

    from yoke_core.domain.item_dependency import cmd_dependency_update

    try:
        result = _run_with_conn(
            cmd_dependency_update,
            dependent,
            body.blocking_item,
            match_gate_point=body.match_gate_point,
            gate_point=body.gate_point,
            satisfaction=body.satisfaction,
            rationale=body.rationale,
        )
    except (LookupError, ValueError, RuntimeError) as exc:
        return _domain_error(exc)
    return HandlerOutcome(
        result_payload={
            "dependent_item": dependent,
            "blocking_item": body.blocking_item,
            "result": result,
        },
        primary_success=True,
    )


def handle_item_dependency_remove(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    body, err = _validate(
        ItemDependencyRemoveRequest, request.payload, "dependency_remove",
    )
    if err is not None:
        return err
    dependent, err = _dependent_item(request)
    if err is not None:
        return err
    assert dependent is not None

    from yoke_core.domain.item_dependency import cmd_dependency_remove

    try:
        result = _run_with_conn(
            cmd_dependency_remove,
            dependent,
            body.blocking_item,
        )
    except (LookupError, ValueError, RuntimeError) as exc:
        return _domain_error(exc)
    return HandlerOutcome(
        result_payload={
            "dependent_item": dependent,
            "blocking_item": body.blocking_item,
            "result": result,
        },
        primary_success=True,
    )


__all__ = [
    "ItemDependencyAddRequest",
    "ItemDependencyAddResponse",
    "ItemDependencyUpdateRequest",
    "ItemDependencyUpdateResponse",
    "ItemDependencyRemoveRequest",
    "ItemDependencyRemoveResponse",
    "handle_item_dependency_add",
    "handle_item_dependency_update",
    "handle_item_dependency_remove",
]
