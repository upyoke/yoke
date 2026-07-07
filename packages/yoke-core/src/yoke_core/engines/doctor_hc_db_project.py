"""Project integrity health checks (core).

Project-integrity HC functions covering FK integrity, local checkout mapping,
JSON field validity, deployment-flow coverage, and duplicate-projects
detection. Orphan-reference and schema-drift clusters live in focused
sibling modules:

- ``doctor_hc_db_project_orphans`` — orphaned project references in items
  and deployment events, plus orphaned deploy events.
- ``doctor_hc_db_project_schema`` — schema drift detection, schema script
  sync, SQLite integrity, and migration audit evidence.

This module remains the canonical entry point that ``doctor.py`` imports.
It defines the five core project-integrity HCs and re-exports the public
HC functions owned by the orphans and schema siblings so the ``doctor.py``
registration block keeps a single import statement.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.project_checkout_locations import checkout_for_project_id

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

from yoke_core.engines.doctor_hc_db_project_orphans import (  # noqa: F401
    hc_orphaned_project_items,
)
from yoke_core.engines.doctor_hc_db_project_schema import (  # noqa: F401
    hc_migration_audit,
    hc_schema_drift,
    hc_schema_script_sync,
)


def hc_project_fk_integrity(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-project-fk-integrity: Project FK integrity."""
    if not _base._table_exists(conn, "projects"):
        rec.record(
            "HC-project-fk-integrity", "Project FK integrity", "WARN",
            "projects table does not exist yet — run "
            "python3 -m yoke_core.domain.projects init to create the "
            "registry tables (it seeds no project rows), then register "
            "each project via yoke projects create / yoke project install",
        )
        return

    rows = query_rows(
        conn,
        "SELECT i.id, i.project_id FROM items i "
        "WHERE i.project_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM projects p WHERE p.id = i.project_id) "
        "ORDER BY i.id",
    )

    issues = [f"- YOK-{r['id']}: project_id '{r['project_id']}' does not exist in projects table" for r in rows]

    if issues:
        rec.record("HC-project-fk-integrity", "Project FK integrity", "FAIL", "\n".join(issues))
    else:
        rec.record("HC-project-fk-integrity", "Project FK integrity", "PASS", "")



def hc_project_checkout_mapping(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-project-checkout-mapping: Local project checkout mappings."""
    if not _base._table_exists(conn, "projects"):
        rec.record("HC-project-checkout-mapping", "Project checkout mappings", "WARN",
                    "projects table does not exist yet")
        return

    rows = query_rows(conn, "SELECT id, slug FROM projects ORDER BY id")
    issues: List[str] = []
    for row in rows:
        checkout = checkout_for_project_id(int(row["id"]))
        rp = str(checkout) if checkout is not None else ""
        if not rp:
            issues.append(f"- project '{row['slug']}': no machine-local checkout mapping")
        elif not Path(rp).is_dir() or (
            not (Path(rp) / ".git").is_dir()
            and _base._run(["git", "-C", rp, "rev-parse", "--git-dir"], timeout=5).returncode != 0
        ):
            issues.append(f"- project '{row['slug']}': mapped checkout '{rp}' is not a git repository")

    if issues:
        rec.record("HC-project-checkout-mapping", "Project checkout mappings", "WARN", "\n".join(issues))
    else:
        rec.record("HC-project-checkout-mapping", "Project checkout mappings", "PASS", "")



def hc_project_json_validity(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-project-json-validity: Project JSON field validity.

    The coarse project-context JSON columns this HC used to validate were
    retired into the ``context_routing`` Project Structure family. Project
    Structure payloads are validated structurally on every write, so there
    is no drift surface left for this HC to catch on the ``projects`` table.
    Kept as a no-op PASS so the HC registry shape is stable.
    """
    if not _base._table_exists(conn, "projects"):
        rec.record("HC-project-json-validity", "Project JSON field validity", "WARN",
                    "projects table does not exist yet")
        return

    rec.record("HC-project-json-validity", "Project JSON field validity", "PASS", "")



def hc_projects_without_flows(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-projects-without-flows: Projects without deployment flows."""
    if not _base._table_exists(conn, "projects"):
        rec.record("HC-projects-without-flows", "Projects without deployment flows", "PASS",
                    "projects table does not exist yet — skipping")
        return
    if not _base._table_exists(conn, "deployment_flows"):
        rec.record("HC-projects-without-flows", "Projects without deployment flows", "WARN",
                    "deployment_flows table does not exist yet")
        return

    rows = query_rows(
        conn,
        "SELECT p.slug FROM projects p "
        "WHERE NOT EXISTS (SELECT 1 FROM deployment_flows df WHERE df.project_id = p.id) "
        "ORDER BY p.id",
    )
    issues = [f"- project '{r['slug']}' has no deployment flows defined" for r in rows]

    if issues:
        rec.record("HC-projects-without-flows", "Projects without deployment flows", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-projects-without-flows", "Projects without deployment flows", "PASS", "")



def hc_duplicate_projects(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-duplicate-projects: Duplicate project IDs / prefixes."""
    if not _base._table_exists(conn, "projects"):
        rec.record("HC-duplicate-projects", "Duplicate project IDs / prefixes", "PASS",
                    "projects table does not exist yet — skipping")
        return

    issues: List[str] = []
    if _base._column_exists(conn, "projects", "public_item_prefix"):
        rows = query_rows(
            conn,
            "SELECT UPPER(public_item_prefix) AS public_item_prefix, "
            "STRING_AGG(slug, ', ') as slugs FROM projects "
            "WHERE public_item_prefix IS NOT NULL AND public_item_prefix <> '' "
            "GROUP BY UPPER(public_item_prefix) HAVING COUNT(*) > 1",
        )
        for r in rows:
            issues.append(
                f"- public_item_prefix '{r['public_item_prefix']}' shared by "
                f"projects: {r['slugs']}"
            )

    if issues:
        rec.record("HC-duplicate-projects", "Duplicate project IDs / prefixes", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-duplicate-projects", "Duplicate project IDs / prefixes", "PASS", "")
