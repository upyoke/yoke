"""Apply item-identity projection to a dispatcher response.

Every response leaving :func:`yoke_core.domain.yoke_function_dispatch.dispatch`
— handler results and idempotent replays alike — names its items by public
ref beside the engine ids (:mod:`item_identity_projection`). A projection
that cannot run leaves the result as the handler wrote it and says so in a
warning, rather than failing a call whose work already happened.
"""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionCallResponse, FunctionWarning

from yoke_core.domain.item_identity_projection import (
    collect_item_ids,
    project_item_identity,
)


def project_response_item_identity(
    response: FunctionCallResponse,
) -> FunctionCallResponse:
    """Return ``response`` with public refs filled beside its item ids."""
    if not response.result or not collect_item_ids(response.result):
        return response
    from yoke_core.domain import db_helpers

    try:
        with db_helpers.connect() as conn:
            projected = project_item_identity(conn, response.result)
    except Exception as exc:  # noqa: BLE001 - the call's work already happened
        warning = FunctionWarning(
            code="public_ref_projection_failed",
            step="item_identity_projection",
            detail=(
                f"could not render public refs for this response ({exc}); "
                "item ids are unrendered — retry the read"
            ),
        )
        return response.model_copy(update={"warnings": [*response.warnings, warning]})
    return response.model_copy(update={"result": projected})


__all__ = ["project_response_item_identity"]
