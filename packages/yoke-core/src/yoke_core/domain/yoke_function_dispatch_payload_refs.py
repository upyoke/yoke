"""Server-side payload item-ref resolution for the function dispatcher.

A caller names every item a payload refers to by public ref, under a
top-level ``public_ref``-family key (:mod:`item_identity_keys`). Before the
handler runs, the dispatcher resolves each one through
:func:`yoke_core.domain.item_ref_resolution.resolve_item_ref` and replaces
it with the matching ``item_id``-family key the handler's request model
declares, so handlers read internal ids and no caller ever carries one. A
model that declares the ``public_ref``-family key itself takes the ref as
its own input and resolves it in the handler. A bare number resolves only against the
call's explicit project — the ``target.project_id`` hint or a payload
``project`` — and is refused without one.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)

from yoke_core.domain.item_identity_keys import engine_key_for_wire, is_plural


def _error(
    request: FunctionCallRequest, message: str, key: str
) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        error=FunctionError(
            code="public_ref_unresolved",
            message=message,
            jsonpath=f"$.payload.{key}",
        ),
    )


def _project_context(request: FunctionCallRequest, hint: Optional[str]) -> Any:
    if hint:
        return hint
    project = (request.payload or {}).get("project")
    if isinstance(project, (str, int)) and not isinstance(project, bool):
        return project if str(project).strip() else None
    return None


def _agrees(supplied: Any, resolved: Any) -> bool:
    """Whether an engine key the caller also sent names the resolved item(s)."""
    if supplied is None:
        return True
    try:
        if isinstance(resolved, list):
            return [int(value) for value in supplied] == resolved
        return int(supplied) == resolved
    except (TypeError, ValueError):
        return False


def _translated_keys(payload: dict, request_model: Any) -> list[str]:
    fields = getattr(request_model, "model_fields", None) or {}
    keys = []
    for key in payload:
        engine_key = engine_key_for_wire(str(key))
        if engine_key and engine_key in fields and key not in fields:
            keys.append(str(key))
    return keys


def resolve_payload_public_refs(
    request: FunctionCallRequest,
    request_model: Any,
    *,
    project_hint: Optional[str] = None,
) -> Optional[FunctionCallResponse]:
    """Resolve the payload's public-ref keys onto engine keys in place.

    ``project_hint`` is the caller's ``target.project_id`` as it arrived,
    before target resolution consumed it. Returns ``None`` on success or a
    typed refusal naming the key and the fix.
    """
    payload = request.payload
    if not isinstance(payload, dict):
        return None
    wire_keys = _translated_keys(payload, request_model)
    if not wire_keys:
        return None
    from yoke_core.domain import db_helpers
    from yoke_core.domain.item_ref_resolution import ItemRefError, resolve_item_ref

    project = _project_context(request, project_hint)
    resolved: dict[str, Any] = {}
    with db_helpers.connect() as conn:
        for key in wire_keys:
            engine_key = str(engine_key_for_wire(key))
            value = payload[key]
            try:
                if value is None:
                    resolved[engine_key] = None
                elif is_plural(str(key)):
                    if not isinstance(value, list):
                        return _error(
                            request,
                            f"payload.{key} must be a list of public refs (PREFIX-N)",
                            key,
                        )
                    resolved[engine_key] = [
                        resolve_item_ref(conn, ref, project=project) for ref in value
                    ]
                else:
                    resolved[engine_key] = resolve_item_ref(
                        conn, value, project=project
                    )
            except ItemRefError as exc:
                return _error(request, f"payload.{key}: {exc}", key)
            if not _agrees(payload.get(engine_key), resolved[engine_key]):
                return _error(
                    request,
                    (
                        f"payload.{engine_key} names a different item than "
                        f"payload.{key}; send payload.{key} alone"
                    ),
                    key,
                )
    for key in wire_keys:
        del payload[key]
    payload.update(resolved)
    return None


__all__ = ["resolve_payload_public_refs"]
