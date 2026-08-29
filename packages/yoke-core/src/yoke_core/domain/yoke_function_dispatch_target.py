"""Server-side target item-ref resolution for the function dispatcher.

The relay contract (CLI grammar contract) requires that no `yoke` CLI
adapter touch the DB before dispatch: a client carries the raw public
item reference (``PREFIX-N`` or a bare project-local number) on
``target.public_ref`` plus whatever project context it knows client-side
on ``target.project_id``, and the dispatcher resolves the internal
``items.id`` here — identically for in-process and HTTPS callers.

Bare numeric refs resolve only from ``target.project_id`` — the explicit
``--project`` flag or the machine checkout-to-project map supplied by the
client. Missing context produces the parser's loud bare-ref usage error;
session state is not item-identity authority.

``PREFIX-N`` refs resolve through the unique public-prefix ladder in
:func:`yoke_core.domain.yok_n_parser.parse_item_id` regardless of
context.
"""

from __future__ import annotations

from typing import Optional

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)


def resolve_target_public_ref(
    request: FunctionCallRequest,
) -> Optional[FunctionCallResponse]:
    """Resolve ``target.public_ref`` into ``target.item_id`` in place.

    Returns ``None`` on success / no-op; a typed error response when the
    ref cannot be resolved, or when an explicit ``target.item_id`` names
    a different row than ``target.public_ref``. The public ref is always
    resolved when present — a numeric tail stuffed into ``item_id`` must
    not skip that lookup.
    """
    target = request.target
    if target.public_ref is None:
        return None
    from yoke_core.domain import db_helpers
    from yoke_core.domain.yok_n_parser import parse_item_id

    try:
        with db_helpers.connect() as conn:
            resolved = parse_item_id(
                target.public_ref,
                project=target.project_id or None,
                conn=conn,
                allow_bare_internal=False,
            )
    except ValueError as exc:
        return FunctionCallResponse(
            success=False,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            error=FunctionError(
                code="public_ref_unresolved",
                message=f"target.public_ref {target.public_ref!r}: {exc}",
                jsonpath="$.target.public_ref",
            ),
        )
    if target.item_id is not None and int(target.item_id) != int(resolved):
        return FunctionCallResponse(
            success=False,
            function=request.function,
            version=request.version,
            request_id=request.request_id,
            error=FunctionError(
                code="item_id_ref_mismatch",
                message=(
                    f"target.item_id {int(target.item_id)} does not match "
                    f"target.public_ref {target.public_ref!r} "
                    f"(resolves to items.id={int(resolved)})"
                ),
                jsonpath="$.target",
            ),
        )
    target.item_id = int(resolved)
    # The client-side context hint has served its purpose; clear it so
    # permission scoping derives from the resolved item's own project,
    # not the caller's ambient checkout (a PREFIX-N ref may
    # legitimately point at another project).
    target.project_id = None
    return None


__all__ = ["resolve_target_public_ref"]
