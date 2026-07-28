"""Resolve organization authority for dispatched function calls."""

from __future__ import annotations

from typing import Any

from yoke_contracts.api.function_call import FunctionCallRequest

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_project_id


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


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
        f"SELECT org_id FROM projects WHERE id = {_placeholder(conn)}",
        (project_id,),
    ).fetchone()
    if row is None:
        return None
    value = row["org_id"] if hasattr(row, "keys") else row[0]
    return int(value) if value is not None else None


def _identity_card_org(conn: Any) -> int | None:
    """Return the universe's identity-card org (lowest id), or None."""
    row = conn.execute("SELECT id FROM organizations ORDER BY id LIMIT 1").fetchone()
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
            f"SELECT id FROM organizations WHERE id = {_placeholder(conn)}",
            (int(cleaned),),
        ).fetchone()
        if row is None:
            return None
        value = row["id"] if hasattr(row, "keys") else row[0]
        return int(value)
    from yoke_core.domain.org_schema import org_id_by_slug

    return org_id_by_slug(conn, cleaned)


__all__ = ["resolve_org_context"]
