"""Canonical hosted-runtime identity shared by a runtime host and its consumer.

A project may run QA against an environment another project owns only through
the hosted-runtime bridge: the environment sits on the canonical runtime site
of a project in the same organization, declares ``qa.hosted_runtime``, and
names the consuming project in ``qa.hosted_runtime_consumer``. The host
declares the consumer; no project name is fixed in code.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.environment_declared_facts import (
    decode_settings,
    declared_text,
    is_hosted_runtime,
)


CANONICAL_RUNTIME_SITE_NAME = "Yoke API"
QA_HOSTED_RUNTIME_CONSUMER_PATH = "qa.hosted_runtime_consumer"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_dict(cursor: Any, row: Any) -> dict[str, Any]:
    if hasattr(row, "keys"):
        return {str(key): row[key] for key in row.keys()}
    columns = [str(column[0]) for column in cursor.description]
    return dict(zip(columns, row, strict=True))


def _shared_runtime_allowed(row: Mapping[str, Any]) -> bool:
    """Whether *row* is a hosted runtime that declares the plan project its consumer."""
    settings = decode_settings(row.get("settings"))
    return (
        int(row["plan_org_id"]) == int(row["owner_org_id"])
        and str(row["site_name"]) == CANONICAL_RUNTIME_SITE_NAME
        and is_hosted_runtime(settings)
        and declared_text(settings, QA_HOSTED_RUNTIME_CONSUMER_PATH)
        == str(row["plan_project_slug"])
    )


def _environment_allowed(row: Mapping[str, Any]) -> bool:
    if int(row["plan_project_id"]) == int(row["owner_project_id"]):
        return True
    return _shared_runtime_allowed(row)


def require_plan_environment_access(
    conn: Any,
    *,
    plan_project_id: int,
    environment_id: int,
) -> dict[str, Any]:
    """Allow project-owned targets or the exact canonical hosted bridge."""
    marker = _p(conn)
    cursor = conn.execute(
        "SELECT plan.id AS plan_project_id,plan.slug AS plan_project_slug,"
        "plan.org_id AS plan_org_id,owner.id AS owner_project_id,"
        "owner.slug AS owner_project_slug,owner.org_id AS owner_org_id,"
        "s.name AS site_name,e.id AS environment_id,e.name AS environment_name,"
        "e.settings "
        "FROM projects plan JOIN environments e ON e.id="
        f"{marker} JOIN sites s ON s.id=e.site "
        "JOIN projects owner ON owner.id=s.project_id "
        f"WHERE plan.id={marker}",
        (int(environment_id), int(plan_project_id)),
    )
    row = cursor.fetchone()
    if row is None:
        raise ValueError("the selected environment is unavailable")
    result = _row_dict(cursor, row)
    if not _environment_allowed(result):
        raise ValueError(
            f"environment {result['environment_name']!r} is not authorized for "
            f"plan project {plan_project_id}. Recovery: target an environment "
            "the plan project owns, or have the owning project share it from "
            f"its {CANONICAL_RUNTIME_SITE_NAME!r} site by declaring "
            "qa.hosted_runtime=true and "
            f"{QA_HOSTED_RUNTIME_CONSUMER_PATH}={result['plan_project_slug']} "
            "(`yoke projects environment-settings merge`)"
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
        "s.name AS site_name,e.id AS environment_id,e.name AS environment_name,"
        "e.settings "
        "FROM projects plan JOIN sites s ON "
        f"(s.project_id=plan.id OR s.name={marker}) "
        "JOIN environments e ON e.site=s.id "
        "JOIN projects owner ON owner.id=s.project_id "
        f"WHERE plan.id={marker} ORDER BY e.id",
        (CANONICAL_RUNTIME_SITE_NAME, int(plan_project_id)),
    )
    return [
        result
        for row in cursor.fetchall()
        if _environment_allowed(result := _row_dict(cursor, row))
    ]


def _rendered_candidates(rows: list[dict[str, Any]]) -> str:
    """Render every eligible target as the SITE/NAME reference it answers to."""
    return (
        ", ".join(
            sorted(f"{row['site_name']}/{row['environment_name']}" for row in rows)
        )
        or "(none)"
    )


def _default_environment_site(rows: list[dict[str, Any]]) -> str | None:
    """Return the site an unqualified environment name resolves within.

    A project reaching the shared hosted runtime resolves there, because that
    runtime is what its QA executes against, while its own site holds deploy
    targets that may reuse the same names. Any other project resolves
    within its single site, and one owning several needs an explicit reference.
    """
    for row in rows:
        if _shared_runtime_allowed(row):
            return str(row["site_name"])
    sites = {str(row["site_name"]) for row in rows}
    return sites.pop() if len(sites) == 1 else None


def resolve_plan_environment_reference(
    conn: Any,
    *,
    plan_project_id: int,
    environment: str,
) -> dict[str, Any]:
    """Resolve a SITE/NAME reference, an environment id, or a bare name.

    Environment names are unique only inside one site, so a bare name resolves
    within the default site rather than across every eligible site.
    """
    reference = str(environment or "").strip()
    rows = eligible_plan_environment_rows(
        conn,
        plan_project_id=int(plan_project_id),
    )
    rendered = _rendered_candidates(rows)
    if reference.isdigit():
        for row in rows:
            if int(row["environment_id"]) == int(reference):
                return row
        raise ValueError(
            f"environment id {reference} is not registered for plan project "
            f"{plan_project_id}; registered: {rendered}"
        )
    site, separator, name = reference.rpartition("/")
    if not separator:
        site = _default_environment_site(rows) or ""
        if not site:
            raise ValueError(
                f"environment {reference!r} needs a SITE/NAME reference or an "
                f"environment id for plan project {plan_project_id}; "
                f"registered: {rendered}"
            )
    for row in rows:
        if str(row["site_name"]) == site and str(row["environment_name"]) == name:
            return row
    raise ValueError(
        f"environment {site}/{name} is not registered for plan project "
        f"{plan_project_id}; registered: {rendered}"
    )


__all__ = [
    "CANONICAL_RUNTIME_SITE_NAME",
    "QA_HOSTED_RUNTIME_CONSUMER_PATH",
    "eligible_plan_environment_rows",
    "resolve_plan_environment_reference",
    "require_plan_environment_access",
]
