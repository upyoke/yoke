"""Resolve the target project / org for a dispatched function call.

Split from :mod:`yoke_core.domain.yoke_function_permissions` (which owns the
scope routing) to keep each module under the authored-file line cap. These
helpers turn a request's payload/target hints into the concrete project or org
the permission check runs against. There is NO fallback: a project-scoped op
that cannot name its target resolves to ``None`` and is denied upstream (never
silently aimed at the yoke project).
"""

from __future__ import annotations

from typing import Any, Collection

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import (
    AmbiguousProjectRefError,
    resolve_project_id,
)
from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_core.domain.yoke_function_registry import RegistryEntry


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def resolve_project_context(
    conn: Any,
    entry: RegistryEntry,
    request: FunctionCallRequest,
    *,
    visible_project_ids: Collection[int] | None = None,
) -> tuple[int, str] | None:
    """Resolve the real target project for a PROJECT-scoped op (or None)."""
    if entry.function_id == "ephemeral_env.update":
        return _resolve_ephemeral_env_project_context(conn, request)
    if entry.function_id.startswith("github_actions."):
        return _resolve_github_actions_project_context(
            conn, request, visible_project_ids=visible_project_ids,
        )
    if entry.function_id in _PAYLOAD_NAMED_PROJECT_FUNCTIONS:
        return _resolve_named_project_context(
            conn, request, visible_project_ids=visible_project_ids,
        )
    target = request.target
    explicit = target.project_id or request.payload.get("project_id") or request.payload.get("project")
    if explicit:
        try:
            project_id = _resolve_authorized_project_id(
                conn, str(explicit), visible_project_ids,
            )
        except AmbiguousProjectRefError:
            raise
        except LookupError:
            return None
        return project_id, _slug_for_project_id(conn, project_id)
    item_id = target.item_id or target.epic_id
    if item_id is not None:
        p = _p(conn)
        row = conn.execute(
            "SELECT p.id, p.slug "
            "FROM items i "
            "JOIN projects p ON p.id = i.project_id "
            f"WHERE i.id = {p}",
            (int(item_id),),
        ).fetchone()
        if row is not None:
            return int(row[0]), str(row[1])
    if target.qa_requirement_id is not None:
        qa_project = _resolve_qa_requirement_project_context(
            conn, int(target.qa_requirement_id),
        )
        if qa_project is not None:
            return qa_project
    # No project hint resolved. Authority is the actor's identity, not a default
    # project — a project-scoped op that cannot name its target is denied
    # upstream (no "fall back to yoke" guess).
    return None


# Functions whose target project lives in the payload (not the target ref):
# projects.update names it by ``slug``; board reads name it by ``scope``.
_PAYLOAD_NAMED_PROJECT_FUNCTIONS = frozenset({
    "projects.update",
    "board.data.get",
    "board.rebuild.run",
})


def _resolve_github_actions_project_context(
    conn: Any,
    request: FunctionCallRequest,
    *,
    visible_project_ids: Collection[int] | None = None,
) -> tuple[int, str] | None:
    """Resolve GitHub Actions authority from the handler's project payload.

    GitHub Actions handlers use ``payload.project`` to select both the GitHub
    App installation and repository binding. Authorization must therefore use
    that same project. A target hint is optional, but when supplied it must
    resolve to the identical project rather than selecting a different scope
    for the permission check.
    """
    payload_ref = str(request.payload.get("project") or "").strip()
    if not payload_ref:
        return None
    try:
        project_id = _resolve_authorized_project_id(
            conn, payload_ref, visible_project_ids,
        )
        target_ref = str(request.target.project_id or "").strip()
        if target_ref and resolve_project_id(conn, target_ref) != project_id:
            return None
    except AmbiguousProjectRefError:
        raise
    except LookupError:
        return None
    return project_id, _slug_for_project_id(conn, project_id)


def _resolve_named_project_context(
    conn: Any,
    request: FunctionCallRequest,
    *,
    visible_project_ids: Collection[int] | None = None,
) -> tuple[int, str] | None:
    """Resolve a project op's target from a payload field that names the project.

    Covers ops that carry their target project in the payload rather than the
    target ref — ``projects.*`` by ``slug``, ``board.*`` by ``scope``.
    """
    ref = (
        request.payload.get("slug")
        or request.payload.get("scope")
        or request.payload.get("project")
        or request.payload.get("project_id")
    )
    if not ref:
        return None
    try:
        project_id = _resolve_authorized_project_id(
            conn, str(ref), visible_project_ids,
        )
    except AmbiguousProjectRefError:
        raise
    except LookupError:
        return None
    return project_id, _slug_for_project_id(conn, project_id)


def _resolve_authorized_project_id(
    conn: Any,
    ref: str,
    visible_project_ids: Collection[int] | None,
) -> int:
    if visible_project_ids is None or str(ref).isdigit():
        return resolve_project_id(conn, ref)
    try:
        return resolve_project_id(
            conn, ref, visible_project_ids=visible_project_ids,
        )
    except AmbiguousProjectRefError:
        raise
    except LookupError:
        return resolve_project_id(conn, ref)


def _resolve_qa_requirement_project_context(
    conn: Any,
    qa_requirement_id: int,
) -> tuple[int, str] | None:
    p = _p(conn)
    try:
        row = conn.execute(
            "SELECT p.id, p.slug "
            "FROM qa_requirements q "
            "JOIN items i ON i.id = COALESCE(q.item_id, q.epic_id) "
            "JOIN projects p ON p.id = i.project_id "
            f"WHERE q.id = {p}",
            (qa_requirement_id,),
        ).fetchone()
    except db_backend.database_error_types():
        return None
    if row is None:
        return None
    return int(row[0]), str(row[1])


def _resolve_ephemeral_env_project_context(
    conn: Any,
    request: FunctionCallRequest,
) -> tuple[int, str] | None:
    try:
        env_id = int(request.payload.get("env_id"))
    except (TypeError, ValueError):
        return None
    p = _p(conn)
    row = conn.execute(
        "SELECT p.id, p.slug "
        "FROM ephemeral_environments ee "
        "JOIN projects p ON p.id = ee.project_id "
        f"WHERE ee.id = {p}",
        (env_id,),
    ).fetchone()
    if row is None:
        return None
    return int(row[0]), str(row[1])


def _slug_for_project_id(conn: Any, project_id: int) -> str:
    p = _p(conn)
    row = conn.execute(
        f"SELECT slug FROM projects WHERE id = {p}",
        (project_id,),
    ).fetchone()
    if row is None:
        return str(project_id)
    return str(row[0])


def resolve_org_context(conn: Any, request: FunctionCallRequest) -> int | None:
    """Resolve the target org for an org-scoped op.

    Requests may name an org directly. Otherwise the org is the owning org of
    the named project (``payload.project`` / ``target.project_id``), or absent
    an explicit project, yoke's org (the default org in the single-org world).
    A universe with no yoke project (a fresh self-host install before any
    project onboarding) falls back to its identity-card org — only when the
    request named NO project or org; an explicit ref that fails still refuses.
    """
    target = request.target
    explicit_org = request.payload.get("org_id") or request.payload.get("org")
    if explicit_org:
        return _resolve_explicit_org(conn, str(explicit_org))
    explicit = (
        target.project_id
        or request.payload.get("project_id")
        or request.payload.get("project")
    )
    ref = str(explicit) if explicit else "yoke"
    try:
        project_id = resolve_project_id(conn, ref)
    except Exception:
        if explicit:
            return None
        return _identity_card_org(conn)
    row = conn.execute(
        f"SELECT org_id FROM projects WHERE id = {_p(conn)}",
        (project_id,),
    ).fetchone()
    if row is None:
        return None
    value = row["org_id"] if hasattr(row, "keys") else row[0]
    return int(value) if value is not None else None


def _identity_card_org(conn: Any) -> int | None:
    """Return the universe's identity-card org (lowest id), or None."""
    row = conn.execute(
        "SELECT id FROM organizations ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    value = row["id"] if hasattr(row, "keys") else row[0]
    return int(value)


def _resolve_explicit_org(conn: Any, ref: str) -> int | None:
    cleaned = str(ref or "").strip()
    if not cleaned:
        return None
    if cleaned.isdigit():
        row = conn.execute(
            f"SELECT id FROM organizations WHERE id = {_p(conn)}",
            (int(cleaned),),
        ).fetchone()
        if row is None:
            return None
        value = row["id"] if hasattr(row, "keys") else row[0]
        return int(value)
    from yoke_core.domain.org_schema import org_id_by_slug

    return org_id_by_slug(conn, cleaned)


__all__ = [
    "resolve_project_context",
    "resolve_org_context",
]
