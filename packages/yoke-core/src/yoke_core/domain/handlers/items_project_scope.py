"""Project scoping shared by the items roster read and the items search.

Both reads answer within the same boundary: the caller may name a project
explicitly, and an actor with recorded grants may only ever see the projects
those grants cover. Keeping the boundary in one module means a read cannot
accidentally widen it by reimplementing the scoping.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.actor_project_visibility import (
    actor_visible_project_ids,
    numeric_actor_id,
)


def actor_visible_scope(
    conn: Any,
    request: FunctionCallRequest,
) -> Optional[set[int]]:
    """Project ids this request's actor may see, or ``None`` when unrestricted.

    An empty set means the actor has grants but none that reach a project —
    every scoped read answers empty rather than unrestricted.
    """
    actor = request.actor.actor_id if request.actor else None
    return actor_visible_project_ids(conn, numeric_actor_id(actor))


def resolve_visible_project_id(
    conn: Any,
    project: Optional[str],
    visible_project_ids: Optional[set[int]],
) -> Optional[int]:
    """Resolve an explicit project reference within the visible set.

    Returns ``None`` when no project was named, or when the named project is
    outside the actor's visibility — callers answer empty for the latter
    rather than falling back to an unscoped read.
    """
    if project is None:
        return None
    from yoke_core.domain.project_identity import resolve_project

    ident = resolve_project(
        conn, project, required=False, visible_project_ids=visible_project_ids,
    )
    return None if ident is None else ident.id


def resolve_visible_project_ids(
    conn: Any,
    projects: Optional[list[str]],
    visible_project_ids: Optional[set[int]],
) -> Optional[list[int]]:
    """Resolve several project references within the actor's visible set.

    The multi-project shape of :func:`resolve_visible_project_id`, for a
    reader that names a set of projects in one request instead of one call
    per member. Returns ``None`` when no project was named, and drops any
    named project outside the actor's visibility — so an unresolvable member
    narrows the answer rather than widening it. A list that resolves to
    nothing stays an empty list, which every scoped read answers empty; only
    ``None`` means unrestricted.
    """
    if projects is None:
        return None
    resolved: list[int] = []
    for project in projects:
        project_id = resolve_visible_project_id(
            conn, project, visible_project_ids,
        )
        if project_id is not None and project_id not in resolved:
            resolved.append(project_id)
    return resolved


def ambiguous_project_error(message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(
            code="ambiguous_project",
            message=message,
            jsonpath=jsonpath,
        ),
    )


__all__ = [
    "actor_visible_scope",
    "ambiguous_project_error",
    "resolve_visible_project_id",
    "resolve_visible_project_ids",
]
