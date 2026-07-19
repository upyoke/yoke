"""Database projection for the Pack catalog and project-local receipts."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from yoke_core.domain import db_helpers, json_helper
from yoke_core.domain.pack_catalog import catalog_rows
from yoke_core.domain.project_identity import resolve_project


PACK_CATALOG_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS pack_catalog (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    latest_version TEXT NOT NULL,
    dependencies_json TEXT NOT NULL, -- -> JSONB on Postgres
    documentation TEXT NOT NULL,
    file_count INTEGER NOT NULL,
    observed_at TEXT NOT NULL
)
"""

PROJECT_PACK_REPORTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS project_pack_reports (
    project_id INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    receipt_digest TEXT NOT NULL,
    pack_count INTEGER NOT NULL,
    reported_at TEXT NOT NULL
)
"""

PROJECT_PACK_REPORT_ENTRIES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS project_pack_report_entries (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    pack_slug TEXT NOT NULL,
    installed_version TEXT NOT NULL,
    file_count INTEGER NOT NULL,
    PRIMARY KEY (project_id, pack_slug)
)
"""

PACK_REPORT_FRESHNESS = timedelta(days=1)


class PackProjectionError(RuntimeError):
    """Pack projection input is invalid; the message names the repair."""


def create_pack_projection_tables(conn: Any) -> None:
    """Create the additive Pack projection tables."""

    conn.execute(PACK_CATALOG_TABLE_SQL)
    conn.execute(PROJECT_PACK_REPORTS_TABLE_SQL)
    conn.execute(PROJECT_PACK_REPORT_ENTRIES_TABLE_SQL)


def converge_pack_catalog(conn: Any) -> None:
    """Project the Pack descriptors shipped by this server build into the DB."""

    create_pack_projection_tables(conn)
    now = db_helpers.iso8601_now()
    for row in catalog_rows():
        conn.execute(
            "INSERT INTO pack_catalog("
            "slug,name,description,latest_version,dependencies_json,documentation,"
            "file_count,observed_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(slug) DO UPDATE SET "
            "name=EXCLUDED.name, description=EXCLUDED.description, "
            "latest_version=EXCLUDED.latest_version, "
            "dependencies_json=EXCLUDED.dependencies_json, "
            "documentation=EXCLUDED.documentation, "
            "file_count=EXCLUDED.file_count, observed_at=EXCLUDED.observed_at",
            (
                row["slug"],
                row["name"],
                row["description"],
                row["latest_version"],
                json_helper.dumps_compact(row["dependencies"]),
                row["documentation"],
                row["file_count"],
                now,
            ),
        )


def report_project_packs(
    conn: Any,
    *,
    project: str,
    packs: Iterable[Mapping[str, Any]],
    receipt_digest: str,
) -> dict[str, Any]:
    """Replace one project's DB projection with its repository receipt."""

    identity = resolve_project(conn, project, required=False)
    if identity is None:
        raise PackProjectionError(f"project {project!r} not found")
    rows = [_validate_report_row(row) for row in packs]
    slugs = [row["slug"] for row in rows]
    if len(slugs) != len(set(slugs)):
        raise PackProjectionError("Pack report contains duplicate slugs")
    now = db_helpers.iso8601_now()
    conn.execute(
        "DELETE FROM project_pack_report_entries WHERE project_id=%s", (identity.id,)
    )
    for row in rows:
        conn.execute(
            "INSERT INTO project_pack_report_entries("
            "project_id,pack_slug,installed_version,file_count"
            ") VALUES(%s,%s,%s,%s)",
            (
                identity.id,
                row["slug"],
                row["version"],
                row["file_count"],
            ),
        )
    conn.execute(
        "INSERT INTO project_pack_reports("
        "project_id,receipt_digest,pack_count,reported_at"
        ") VALUES(%s,%s,%s,%s) ON CONFLICT(project_id) DO UPDATE SET "
        "receipt_digest=EXCLUDED.receipt_digest, pack_count=EXCLUDED.pack_count, "
        "reported_at=EXCLUDED.reported_at",
        (identity.id, receipt_digest, len(rows), now),
    )
    return {
        "project_id": identity.id,
        "project_slug": identity.slug,
        "reported": len(rows),
        "reported_at": now,
        "receipt_digest": receipt_digest,
    }


def list_project_pack_status(conn: Any, *, project: str) -> dict[str, Any]:
    """Return Available/Installed/Stale Pack rows for one project."""

    identity = resolve_project(conn, project, required=False)
    if identity is None:
        raise PackProjectionError(f"project {project!r} not found")
    rows = conn.execute(
        "SELECT c.slug,c.name,c.description,c.latest_version,c.dependencies_json,"
        "c.documentation,c.file_count,c.observed_at,r.installed_version,"
        "r.file_count AS installed_file_count,"
        "h.reported_at,h.receipt_digest,h.pack_count FROM pack_catalog c "
        "LEFT JOIN project_pack_reports h ON h.project_id=%s "
        "LEFT JOIN project_pack_report_entries r "
        "ON r.pack_slug=c.slug AND r.project_id=%s ORDER BY c.slug",
        (identity.id, identity.id),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        installed = _row(row, "installed_version")
        latest = str(_row(row, "latest_version"))
        reported_at = _row(row, "reported_at")
        stale_reasons: list[str] = []
        if installed and installed != latest:
            stale_reasons.append("update_available")
        if installed and not _report_is_fresh(reported_at):
            stale_reasons.append("repository_report_expired")
        status = "available" if not installed else "stale" if stale_reasons else "installed"
        dependencies = json_helper.loads_text(str(_row(row, "dependencies_json") or "[]"))
        result.append(
            {
                "slug": _row(row, "slug"),
                "name": _row(row, "name"),
                "description": _row(row, "description"),
                "status": status,
                "installed_version": installed,
                "latest_version": latest,
                "dependencies": dependencies,
                "documentation": _row(row, "documentation"),
                "file_count": _row(row, "file_count"),
                "installed_file_count": _row(row, "installed_file_count"),
                "catalog_observed_at": _row(row, "observed_at"),
                "reported_at": reported_at,
                "stale_reasons": stale_reasons,
                "receipt_digest": _row(row, "receipt_digest"),
            }
        )
    report = conn.execute(
        "SELECT receipt_digest,pack_count,reported_at FROM project_pack_reports "
        "WHERE project_id=%s",
        (identity.id,),
    ).fetchone()
    return {
        "project_id": identity.id,
        "project_slug": identity.slug,
        "repository_report": (
            {
                "receipt_digest": _row(report, "receipt_digest"),
                "pack_count": _row(report, "pack_count"),
                "reported_at": _row(report, "reported_at"),
                "fresh": _report_is_fresh(_row(report, "reported_at")),
            }
            if report is not None
            else None
        ),
        "packs": result,
    }


def receipt_digest(receipt_bytes: bytes) -> str:
    return hashlib.sha256(receipt_bytes).hexdigest()


def _validate_report_row(row: Mapping[str, Any]) -> dict[str, Any]:
    slug = str(row.get("slug") or "").strip()
    version = str(row.get("version") or "").strip()
    file_count = row.get("file_count")
    if not slug or not version or not isinstance(file_count, int) or file_count < 0:
        raise PackProjectionError("Pack report rows require slug, version, and file_count")
    return {"slug": slug, "version": version, "file_count": file_count}


def _row(row: Any, key: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    return row[key]


def _report_is_fresh(raw: Any) -> bool:
    if not raw:
        return False
    try:
        observed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - observed.astimezone(timezone.utc) <= PACK_REPORT_FRESHNESS


__all__ = [
    "PACK_CATALOG_TABLE_SQL",
    "PROJECT_PACK_REPORTS_TABLE_SQL",
    "PROJECT_PACK_REPORT_ENTRIES_TABLE_SQL",
    "PACK_REPORT_FRESHNESS",
    "PackProjectionError",
    "converge_pack_catalog",
    "create_pack_projection_tables",
    "list_project_pack_status",
    "receipt_digest",
    "report_project_packs",
]
