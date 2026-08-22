"""Server-side project resolution shared by project-scoped handlers.

Consumed by the ``strategy.*`` family and
``projects.checkout_context.run``.

The relay contract: the CLI resolves project context client-side
(``--project`` flag > ``$YOKE_PROJECT`` > the machine-config
checkout→project map) and carries it on ``target.project_id``; the
server resolves that raw ref (numeric id or slug) into the canonical
``projects`` row here. When the client sent nothing, the typed
``project_context_required`` error teaches the ``--project`` recipe. The
server never resolves an ambient cwd or guesses from session state.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from yoke_core.domain.project_identity import ProjectIdentity, resolve_project
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


def _error(code: str, message: str, *, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        result_payload={},
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def resolve_request_project(
    conn: Any, request: FunctionCallRequest,
) -> Tuple[Optional[ProjectIdentity], Optional[HandlerOutcome]]:
    """Return ``(project, None)`` or ``(None, typed_error_outcome)``."""
    raw = request.target.project_id
    if raw is None or not str(raw).strip():
        return None, _error(
            "project_context_required",
            "no project context: pass --project <slug-or-id> (or run "
            "from a checkout mapped in machine config — `yoke project "
            "register` records the mapping). The command is "
            "project-scoped; the server never guesses.",
            jsonpath="$.target.project_id",
        )
    try:
        project = resolve_project(conn, raw, required=True)
    except LookupError:
        return None, _error(
            "project_not_found",
            f"project {raw!r} has no projects row; list projects via "
            "`yoke projects get --help` or register the checkout with "
            "`yoke project register`.",
            jsonpath="$.target.project_id",
        )
    assert project is not None
    return project, None


__all__ = ["resolve_request_project"]
