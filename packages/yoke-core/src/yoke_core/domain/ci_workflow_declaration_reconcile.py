"""Reconcile a declared ``ci_workflow_file`` against the project checkout.

A declaration is load-bearing: deploy and QA gates consume the filename
without asking whether the file exists. This helper is the recurring
reconciliation — it stamps ``project_capabilities.verified_at`` when the
named file is present under ``.github/workflows/``, and clears that stamp
when the file is absent on a host that holds the checkout.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now, query_rows
from yoke_core.domain.project_checkout_locations import checkout_for_project_id
from yoke_core.domain.projects_seed_ci_workflow import (
    CI_WORKFLOW_CAPABILITY_TYPE,
)


STATUS_RESOLVED = "resolved"
STATUS_MISSING = "missing"
STATUS_NO_CHECKOUT = "no_checkout"
STATUS_UNDECLARED = "undeclared"


def workflow_path_in_checkout(checkout: Path, workflow_file: str) -> Path:
    return Path(checkout) / ".github" / "workflows" / workflow_file


def reconcile_ci_workflow_declarations(
    conn: Any,
    *,
    config_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Inspect every declared CI workflow and stamp ``verified_at``."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = query_rows(
        conn,
        "SELECT p.id AS project_id, p.slug, p.github_repo, pc.settings "
        "FROM project_capabilities pc "
        "JOIN projects p ON p.id = pc.project_id "
        f"WHERE pc.type = {marker} "
        "ORDER BY p.slug",
        (CI_WORKFLOW_CAPABILITY_TYPE,),
    )
    results: list[dict[str, Any]] = []
    now = iso8601_now()
    for row in rows:
        result = _reconcile_one(conn, row, now, config_path=config_path)
        if result is not None:
            results.append(result)
    return results


def _reconcile_one(
    conn: Any,
    row: Any,
    now: str,
    *,
    config_path: str | Path | None,
) -> dict[str, Any] | None:
    project_id = int(row["project_id"])
    settings = _settings(row["settings"])
    workflow_file = str(settings.get("workflow_file") or "").strip()
    base = {
        "project_id": project_id,
        "slug": str(row["slug"]),
        "github_repo": str(row["github_repo"] or ""),
        "workflow_file": workflow_file,
    }
    if not workflow_file:
        _stamp(conn, project_id, None)
        return {**base, "status": STATUS_UNDECLARED}
    checkout = checkout_for_project_id(project_id, config_path=config_path)
    if checkout is None:
        return {**base, "status": STATUS_NO_CHECKOUT}
    path = workflow_path_in_checkout(checkout, workflow_file)
    if path.is_file():
        _stamp(conn, project_id, now)
        return {**base, "status": STATUS_RESOLVED, "path": str(path)}
    _stamp(conn, project_id, None)
    return {**base, "status": STATUS_MISSING, "path": str(path)}


def _settings(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _stamp(conn: Any, project_id: int, verified_at: str | None) -> None:
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        "UPDATE project_capabilities SET verified_at = "
        f"{marker} WHERE project_id = {marker} AND type = {marker}",
        (verified_at, project_id, CI_WORKFLOW_CAPABILITY_TYPE),
    )


__all__ = [
    "STATUS_MISSING",
    "STATUS_NO_CHECKOUT",
    "STATUS_RESOLVED",
    "STATUS_UNDECLARED",
    "reconcile_ci_workflow_declarations",
    "workflow_path_in_checkout",
]
