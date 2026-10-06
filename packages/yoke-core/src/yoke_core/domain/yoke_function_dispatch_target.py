"""Server-side target item-ref resolution for the function dispatcher.

The relay contract (CLI grammar contract) requires that no `yoke` CLI
adapter touch the DB before dispatch: a client carries the raw public
item reference (``PREFIX-N``) on
``target.public_ref`` plus whatever project context it knows client-side
on ``target.project_id``, and the dispatcher resolves the internal id
here through :func:`yoke_core.domain.item_ref_resolution.resolve_item_ref`
— identically for in-process and HTTPS callers, and for every target
kind. An ``epic_task`` target's ref names its epic, so it fills
``target.epic_id``; every other kind fills ``target.item_id``.

Bare numeric refs resolve only from ``target.project_id`` — the explicit
``--project`` flag or the machine checkout-to-project map supplied by the
client. Missing context is refused with the fix named; session state is
not item-identity authority.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)


def _error(
    request: FunctionCallRequest,
    code: str,
    message: str,
    jsonpath: str,
) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=request.function,
        version=request.version,
        request_id=request.request_id,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def resolve_target_public_ref(
    request: FunctionCallRequest,
) -> Optional[FunctionCallResponse]:
    """Resolve ``target.public_ref`` into the target's internal id in place.

    Returns ``None`` on success / no-op; a typed error response when the
    ref cannot be resolved, or when an explicit internal id on the target
    names a different item than ``target.public_ref``. The public ref is
    always resolved when present — a numeric tail stuffed into the id slot
    must not skip that lookup.
    """
    target = request.target
    if target.public_ref is None:
        return None
    from yoke_core.domain import db_helpers
    from yoke_core.domain.item_ref_resolution import ItemRefError, resolve_item_ref

    try:
        with db_helpers.connect() as conn:
            resolved = resolve_item_ref(
                conn,
                target.public_ref,
                project=target.project_id or None,
            )
    except ItemRefError as exc:
        return _error(
            request,
            "public_ref_unresolved",
            f"target.public_ref {target.public_ref!r}: {exc}",
            "$.target.public_ref",
        )
    slot = "epic_id" if target.kind == "epic_task" else "item_id"
    supplied = getattr(target, slot)
    if supplied is not None and int(supplied) != int(resolved):
        return _error(
            request,
            "item_id_ref_mismatch",
            (
                f"target.{slot} names a different item than target.public_ref "
                f"{target.public_ref!r}; send target.public_ref alone"
            ),
            "$.target",
        )
    setattr(target, slot, int(resolved))
    # The client-side context hint has served its purpose; clear it so
    # permission scoping derives from the resolved item's own project,
    # not the caller's ambient checkout (a PREFIX-N ref may
    # legitimately point at another project).
    target.project_id = None
    return None


def resolve_request_item_refs(
    request: FunctionCallRequest,
    request_model: Any,
) -> Optional[FunctionCallResponse]:
    """Resolve every caller item ref on ``request`` — target, then payload.

    The payload's bare numbers read the caller's ``target.project_id`` as it
    arrived, before target resolution consumes it.
    """
    from yoke_core.domain.yoke_function_dispatch_payload_refs import (
        resolve_payload_public_refs,
    )

    project_hint = request.target.project_id
    refused = resolve_target_public_ref(request)
    if refused is not None:
        return refused
    return resolve_payload_public_refs(
        request,
        request_model,
        project_hint=project_hint,
    )


__all__ = ["resolve_request_item_refs", "resolve_target_public_ref"]
