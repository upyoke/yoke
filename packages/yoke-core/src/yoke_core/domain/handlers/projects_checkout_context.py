"""``projects.checkout_context.run`` handler — which project am I in.

The strategize/feed skill preambles pin ``$_project`` / ``$_project_id``
/ ``$_prefix`` before scoping claims, SQL, and event emissions. The CLI
adapter resolves the checkout→project mapping CLIENT-side (``--project``
flag > ``$YOKE_PROJECT`` > the machine-config checkout→project map)
and carries it on ``target.project_id``; this handler enriches that
hint with DB truth via the shared project ladder (explicit hint →
session inference → typed ``project_context_required`` teaching). The
server never resolves an ambient cwd, so the same envelope works
in-process and over https from any checkout.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from yoke_core.domain.handlers.strategy_docs_project import (
    resolve_request_project,
)
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.project_context import CHECKOUT_CONTEXT_FIELDS


class ProjectsCheckoutContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectsCheckoutContextResponse(BaseModel):
    id: int
    slug: str
    name: str
    public_item_prefix: str


def handle_projects_checkout_context(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    if request.target.kind != "global":
        return HandlerOutcome(
            result_payload={},
            primary_success=False,
            error=FunctionError(
                code="invalid_payload",
                message=(
                    "target.kind must be 'global' "
                    "(projects.checkout_context.run has no item binding; "
                    "project context rides on target.project_id)"
                ),
                jsonpath="$.target.kind",
            ),
        )
    try:
        ProjectsCheckoutContextRequest.model_validate(request.payload or {})
    except Exception as exc:
        return HandlerOutcome(
            result_payload={},
            primary_success=False,
            error=FunctionError(
                code="invalid_payload",
                message=f"payload invalid: {exc}",
                jsonpath="$.payload",
            ),
        )

    from yoke_core.domain.db_helpers import connect

    with connect() as conn:
        project, perr = resolve_request_project(conn, request)
        if perr is not None:
            return perr
    return HandlerOutcome(
        result_payload=ProjectsCheckoutContextResponse(
            id=project.id,
            slug=project.slug,
            name=project.name,
            public_item_prefix=project.public_item_prefix,
        ).model_dump(),
        primary_success=True,
    )


__all__ = [
    "CHECKOUT_CONTEXT_FIELDS",
    "ProjectsCheckoutContextRequest",
    "ProjectsCheckoutContextResponse",
    "handle_projects_checkout_context",
]
