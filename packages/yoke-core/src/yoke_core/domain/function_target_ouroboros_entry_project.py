"""Name the project an ouroboros-entry request is aimed at.

Split from the general target resolver to keep each module inside the
authored-file limit; the rule is unchanged — the entry row records its own
project, and an explicitly named one still wins over it.
"""

from __future__ import annotations

from typing import Any, Collection

from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_core.domain.function_target_row_project import (
    resolve_authorized_project_id,
    resolve_ouroboros_entry_project,
    slug_for_project_id,
)
from yoke_core.domain.project_identity import AmbiguousProjectRefError


def resolve_ouroboros_entry_context(
    conn: Any,
    request: FunctionCallRequest,
    *,
    visible_project_ids: Collection[int] | None = None,
) -> tuple[int, str] | None:
    """Resolve an entry-targeted Ouroboros op's project from the entry row.

    The row is the authority: a caller's project — ``--project``, or the
    ambient checkout the client CLI attaches — may confirm it but never
    redirect it, so an id from one project can't be written while authorized
    as another. Only an entry belonging to no project falls through to the
    caller's, since no row authority exists to prefer.
    """
    try:
        entry_id = int(request.payload["entry_id"])
    except (TypeError, ValueError):
        return None
    row_context = resolve_ouroboros_entry_project(conn, entry_id)
    hint = (
        request.target.project_id
        or request.payload.get("project_id")
        or request.payload.get("project")
    )
    if hint:
        try:
            hinted_id = resolve_authorized_project_id(
                conn,
                str(hint),
                visible_project_ids,
            )
        except AmbiguousProjectRefError:
            raise
        except LookupError:
            return None
        if row_context is not None and hinted_id != row_context[0]:
            return None
        if row_context is None:
            return hinted_id, slug_for_project_id(conn, hinted_id)
    return row_context


__all__ = ["resolve_ouroboros_entry_context"]
