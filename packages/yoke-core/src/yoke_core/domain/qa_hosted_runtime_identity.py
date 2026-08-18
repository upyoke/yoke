"""Canonical hosted-runtime identity shared by Yoke and its Platform host."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain import db_backend


CANONICAL_RUNTIME_SITE_ID = "yoke-api"
CANONICAL_RUNTIME_SITE_NAME = "Yoke API"
CONSUMER_PROJECT_SLUG = "yoke"
HOST_PROJECT_SLUG = "platform"
#: The hosted runtimes, named exactly as their environment rows are. A value
#: that is not one of these is not a hosted runtime; it is not translated.
HOSTED_RUNTIME_NAMES = frozenset({"prod", "stage"})


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def normalize_runtime(value: Any) -> str | None:
    selected = str(value or "").strip().lower()
    return selected if selected in HOSTED_RUNTIME_NAMES else None


def canonical_environment_id(runtime: Any) -> str | None:
    selected = normalize_runtime(runtime)
    return f"{CANONICAL_RUNTIME_SITE_ID}-{selected}" if selected else None


def _row_dict(cursor: Any, row: Any) -> dict[str, Any]:
    if hasattr(row, "keys"):
        return {str(key): row[key] for key in row.keys()}
    columns = [str(column[0]) for column in cursor.description]
    return dict(zip(columns, row, strict=True))


def _shared_runtime_allowed(row: Mapping[str, Any]) -> bool:
    return (
        str(row["plan_project_slug"]) == CONSUMER_PROJECT_SLUG
        and str(row["owner_project_slug"]) == HOST_PROJECT_SLUG
        and int(row["plan_org_id"]) == int(row["owner_org_id"])
        and str(row["site_id"]) == CANONICAL_RUNTIME_SITE_ID
    )


def _environment_allowed(row: Mapping[str, Any]) -> bool:
    if int(row["plan_project_id"]) == int(row["owner_project_id"]):
        return True
    return _shared_runtime_allowed(row) and str(
        row["environment_id"]
    ) == canonical_environment_id(row["environment_name"])


def require_plan_environment_access(
    conn: Any,
    *,
    plan_project_id: int,
    environment_id: str,
) -> dict[str, Any]:
    """Allow project-owned targets or the exact canonical hosted bridge."""
    marker = _p(conn)
    cursor = conn.execute(
        "SELECT plan.id AS plan_project_id,plan.slug AS plan_project_slug,"
        "plan.org_id AS plan_org_id,owner.id AS owner_project_id,"
        "owner.slug AS owner_project_slug,owner.org_id AS owner_org_id,"
        "s.id AS site_id,e.id AS environment_id,e.name AS environment_name "
        "FROM projects plan JOIN environments e ON e.id="
        f"{marker} JOIN sites s ON s.id=e.site "
        "JOIN projects owner ON owner.id=s.project_id "
        f"WHERE plan.id={marker}",
        (str(environment_id), int(plan_project_id)),
    )
    row = cursor.fetchone()
    if row is None:
        raise ValueError(f"environment {environment_id!r} is unavailable")
    result = _row_dict(cursor, row)
    if not _environment_allowed(result):
        raise ValueError(
            f"environment {environment_id!r} is not authorized for "
            f"plan project {plan_project_id}"
        )
    return result


def eligible_plan_environment_rows(
    conn: Any,
    *,
    plan_project_id: int,
) -> list[dict[str, Any]]:
    """Return project-owned targets plus the exact canonical hosted target."""
    marker = _p(conn)
    cursor = conn.execute(
        "SELECT plan.id AS plan_project_id,plan.slug AS plan_project_slug,"
        "plan.org_id AS plan_org_id,owner.id AS owner_project_id,"
        "owner.slug AS owner_project_slug,owner.org_id AS owner_org_id,"
        "s.id AS site_id,e.id AS environment_id,e.name AS environment_name "
        "FROM projects plan JOIN sites s ON "
        f"(s.project_id=plan.id OR s.id={marker}) "
        "JOIN environments e ON e.site=s.id "
        "JOIN projects owner ON owner.id=s.project_id "
        f"WHERE plan.id={marker} ORDER BY e.id",
        (CANONICAL_RUNTIME_SITE_ID, int(plan_project_id)),
    )
    return [
        result
        for row in cursor.fetchall()
        if _environment_allowed(result := _row_dict(cursor, row))
    ]


def require_runtime_site_owner(
    conn: Any,
    *,
    plan_project_id: int,
) -> int | None:
    """Return the canonical site's allowed owner, or None when it is absent."""
    marker = _p(conn)
    cursor = conn.execute(
        "SELECT plan.id AS plan_project_id,plan.slug AS plan_project_slug,"
        "plan.org_id AS plan_org_id,owner.id AS owner_project_id,"
        "owner.slug AS owner_project_slug,owner.org_id AS owner_org_id,"
        "s.id AS site_id FROM projects plan "
        f"LEFT JOIN sites s ON s.id={marker} "
        "LEFT JOIN projects owner ON owner.id=s.project_id "
        f"WHERE plan.id={marker}",
        (CANONICAL_RUNTIME_SITE_ID, int(plan_project_id)),
    )
    row = cursor.fetchone()
    if row is None:
        raise ValueError(f"plan project {plan_project_id} is unavailable")
    result = _row_dict(cursor, row)
    if result["site_id"] is None:
        return None
    owner_id = int(result["owner_project_id"])
    if owner_id == int(plan_project_id) or _shared_runtime_allowed(result):
        return owner_id
    raise ValueError(
        f"hosted QA site {CANONICAL_RUNTIME_SITE_ID!r} is owned by "
        f"unauthorized project {owner_id}"
    )


__all__ = [
    "CANONICAL_RUNTIME_SITE_ID",
    "CANONICAL_RUNTIME_SITE_NAME",
    "HOSTED_RUNTIME_NAMES",
    "canonical_environment_id",
    "eligible_plan_environment_rows",
    "normalize_runtime",
    "require_plan_environment_access",
    "require_runtime_site_owner",
]
