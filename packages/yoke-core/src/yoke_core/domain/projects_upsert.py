"""Idempotent project-row upsert for onboarding."""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import connect, iso8601_now, query_one, query_scalar
from yoke_core.domain.project_identity import DEFAULT_PUBLIC_ITEM_PREFIX
from yoke_core.domain.project_github_binding_payload import normalize_github_repo
from yoke_core.domain.projects_github_sync_mode import GITHUB_SYNC_BACKLOG_ONLY


def cmd_upsert(
    *,
    slug: str,
    name: str,
    org: Optional[str] = None,
    project_id: Optional[int] = None,
    default_branch: Optional[str] = None,
    github_repo: Optional[str] = None,
    public_item_prefix: Optional[str] = None,
    emoji: Optional[str] = None,
    github_sync_mode: Optional[str] = None,
    db_path: Optional[str] = None,
    mode: str = "create",
) -> dict[str, Any]:
    """Create or update a project row and return the canonical row.

    ``mode`` is the authorization-relevant shape (the public surface splits the
    op so the dispatcher can scope it — see ``function_authz_scope``):

    * ``"create"`` — register a project (org-scoped). Idempotent: a re-run that
      matches an existing slug/id updates its fields rather than failing, so
      re-onboarding is safe.
    * ``"update"`` — edit an *existing* project (project-scoped). Raises
      ``ValueError`` when the project does not already exist.
    """
    if mode not in ("create", "update"):
        raise ValueError(f"mode must be 'create' or 'update', got {mode!r}")
    selected_slug = _clean_required(slug, "slug")
    selected_name = _clean_required(name, "name")
    selected_org = _clean_optional(org)
    selected_id = int(project_id) if project_id is not None else None
    if selected_id is not None and selected_id <= 0:
        raise ValueError("project_id must be a positive integer")
    if mode == "update" and selected_org is not None:
        raise ValueError("org is only valid when creating a project")
    selected_sync_mode: Optional[str] = None
    if _clean_optional(github_sync_mode) is not None:
        from yoke_core.domain.projects_github_sync_mode import (
            validate_github_sync_mode,
        )

        selected_sync_mode = validate_github_sync_mode(github_sync_mode)

    conn = connect(db_path)
    try:
        by_id = _row_by_id(conn, selected_id) if selected_id is not None else None
        target_org_id = (
            _resolve_org_id(conn, selected_org)
            if selected_org is not None else _default_org_id(conn)
        )
        if by_id is not None and selected_org is None and by_id["org_id"] is not None:
            target_org_id = int(by_id["org_id"])
        by_slug = _row_by_slug(conn, selected_slug, target_org_id)
        if by_id is not None and by_slug is not None and by_id["id"] != by_slug["id"]:
            raise ValueError(
                f"slug {selected_slug!r} already belongs to project id {by_slug['id']}"
            )
        if by_id is None and by_slug is not None and selected_id is not None:
            raise ValueError(
                f"project id {selected_id} is not bound to slug {selected_slug!r}"
            )

        existing = by_id or by_slug
        created = existing is None
        if existing is not None and target_org_id is not None:
            existing_org_id = existing["org_id"]
            if existing_org_id is not None and int(existing_org_id) != target_org_id:
                raise ValueError(
                    f"project {selected_slug!r} already belongs to a different org"
                )
        if mode == "update" and existing is None:
            raise ValueError(
                f"project {selected_slug!r} does not exist; use projects.create "
                "to register a new project"
            )
        now = iso8601_now()
        if created:
            inserted_sync_mode = selected_sync_mode or GITHUB_SYNC_BACKLOG_ONLY
            if inserted_sync_mode != GITHUB_SYNC_BACKLOG_ONLY:
                raise ValueError(
                    "github_sync_mode=enabled requires an active, verified "
                    "GitHub App repository binding; create the project as "
                    "backlog_only, bind it, then enable issue sync"
                )
            numeric_id = _insert(
                conn, selected_id, target_org_id, selected_slug, selected_name,
                default_branch, github_repo, public_item_prefix, emoji, now,
                inserted_sync_mode,
            )
        else:
            numeric_id = _update(
                conn, existing, selected_slug, selected_name, default_branch,
                github_repo, public_item_prefix, emoji,
            )
        if selected_sync_mode is not None and not created:
            from yoke_core.domain.projects_github_sync_mode import (
                validate_github_sync_mode_update,
            )

            selected_sync_mode = validate_github_sync_mode_update(
                selected_sync_mode,
                conn=conn,
                project_id=numeric_id,
            )
            conn.execute(
                "UPDATE projects SET github_sync_mode=%s WHERE id=%s",
                (selected_sync_mode, numeric_id),
            )
        from yoke_core.domain.project_policy_capabilities import (
            ensure_default_policy_capabilities,
        )

        capability_report = ensure_default_policy_capabilities(
            conn,
            numeric_id,
            base_branch=_clean_optional(default_branch),
        )
        conn.commit()
        row = _row_by_id(conn, numeric_id)
        return {
            "created": created,
            "project": _row_dict(row),
            "project_policy_capabilities": capability_report,
        }
    finally:
        conn.close()


def _insert(
    conn: Any,
    selected_id: Optional[int],
    org_id: Optional[int],
    slug: str,
    name: str,
    default_branch: Optional[str],
    github_repo: Optional[str],
    public_item_prefix: Optional[str],
    emoji: Optional[str],
    now: str,
    github_sync_mode: str,
) -> int:
    numeric_id = selected_id or int(
        query_scalar(conn, "SELECT COALESCE(MAX(id), 0) + 1 FROM projects") or 1
    )
    conn.execute(
        "INSERT INTO projects "
        "(id, slug, name, emoji, default_branch, github_repo, "
        "public_item_prefix, created_at, org_id, github_sync_mode) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            numeric_id, slug, name, _clean_optional(emoji) or "",
            _clean_optional(default_branch) or "main", _clean_optional(github_repo),
            _clean_optional(public_item_prefix) or DEFAULT_PUBLIC_ITEM_PREFIX, now,
            org_id, github_sync_mode,
        ),
    )
    return numeric_id


def _update(
    conn: Any,
    existing: Any,
    slug: str,
    name: str,
    default_branch: Optional[str],
    github_repo: Optional[str],
    public_item_prefix: Optional[str],
    emoji: Optional[str],
) -> int:
    numeric_id = int(existing["id"])
    selected_github_repo = (
        existing["github_repo"]
        if github_repo is None
        else _binding_guarded_github_repo(conn, numeric_id, github_repo)
    )
    conn.execute(
        "UPDATE projects SET slug=%s, name=%s, emoji=%s, "
        "default_branch=%s, github_repo=%s, public_item_prefix=%s WHERE id=%s",
        (
            slug, name,
            _clean_optional(emoji) if emoji is not None else existing["emoji"],
            _clean_optional(default_branch) or existing["default_branch"] or "main",
            selected_github_repo,
            _clean_optional(public_item_prefix) or existing["public_item_prefix"]
            or DEFAULT_PUBLIC_ITEM_PREFIX,
            numeric_id,
        ),
    )
    return numeric_id


def _binding_guarded_github_repo(
    conn: Any,
    project_id: int,
    github_repo: Optional[str],
) -> Optional[str]:
    """Keep the project repo projection aligned with a verified binding."""
    candidate = _clean_optional(github_repo)
    binding = query_one(
        conn,
        "SELECT github_repo FROM project_github_repo_bindings WHERE project_id=%s",
        (project_id,),
    )
    if binding is None:
        return candidate
    bound_repo = str(binding["github_repo"] or "").strip()
    if (
        not candidate
        or not bound_repo
        or normalize_github_repo(candidate) != normalize_github_repo(bound_repo)
    ):
        raise ValueError(
            "project github_repo is binding-owned and must match the verified "
            "GitHub App repo; rebind the repository to change it"
        )
    return bound_repo


def _row_by_id(conn: Any, project_id: int) -> Any:
    return query_one(conn, "SELECT * FROM projects WHERE id=%s", (project_id,))


def _row_by_slug(conn: Any, slug: str, org_id: Optional[int]) -> Any:
    if org_id is None:
        return query_one(conn, "SELECT * FROM projects WHERE slug=%s", (slug,))
    return query_one(
        conn, "SELECT * FROM projects WHERE org_id=%s AND slug=%s", (org_id, slug)
    )


def _clean_required(value: str, label: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{label} is required")
    return cleaned


def _clean_optional(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned if cleaned else None


def _resolve_org_id(conn: Any, org: str) -> int:
    cleaned = _clean_required(org, "org")
    if cleaned.isdigit():
        row = query_one(
            conn, "SELECT id FROM organizations WHERE id=%s", (int(cleaned),)
        )
        if row is None:
            raise ValueError(f"organization id {cleaned} not found")
        return int(row["id"])
    from yoke_core.domain.org_schema import org_id_by_slug

    org_id = org_id_by_slug(conn, cleaned)
    if org_id is None:
        raise ValueError(f"organization {cleaned!r} not found")
    return org_id


def _default_org_id(conn: Any) -> Optional[int]:
    from yoke_core.domain.org_schema import DEFAULT_ORG_SLUG, org_id_by_slug

    try:
        return org_id_by_slug(conn, DEFAULT_ORG_SLUG)
    except Exception:
        return None


def _row_dict(row: Any) -> dict[str, Any]:
    from yoke_core.domain import projects as parent

    return {field: row[field] for field in parent.PROJECT_FIELDS}


__all__ = ["cmd_upsert"]
