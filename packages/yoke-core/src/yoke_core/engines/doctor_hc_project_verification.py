"""Doctor health check — a project can actually run verification at merge.

HC-project-verification-configured WARNs when a registered project has NEITHER
a ``command_definitions`` test command NOR a ``merge_verification`` policy. Such
a project's merge gate runs ZERO tests — the merge engine reads only
``merge_verification`` and never falls back to a full command — and tester /
advance / polish have no project test command to run either. A freshly
installed external project is in exactly this state until it is onboarded.

WARN, not FAIL: an under-onboarded project should surface loudly without
blocking a green doctor run. PASSes when every project carries a non-empty
command in either family. Self-skips silently when the structure tables are
absent (minimal-schema fixtures).
"""

from __future__ import annotations

from typing import Dict

from yoke_core.domain import json_helper
from yoke_core.domain.db_helpers import query_rows
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _table_exists,
)

CHECK_ID = "project-verification-configured"
CHECK_NAME = "Project has a test command or merge policy"


def _payload_has_command(payload_text) -> bool:
    """True when a structure payload carries a non-empty ``command`` string.

    Both the ``command_definitions`` and ``merge_verification`` families store
    ``{"command": <str>}``; an empty or missing command reads as "not
    configured", matching the family readers.
    """
    if not payload_text:
        return False
    try:
        payload = json_helper.loads_text(payload_text)
    except (ValueError, TypeError):
        return False
    if not isinstance(payload, dict):
        return False
    return bool(str(payload.get("command", "")).strip())


def hc_project_verification_configured(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """HC-project-verification-configured."""
    if not (
        _table_exists(conn, "projects")
        and _table_exists(conn, "project_structure")
    ):
        return

    rows = query_rows(
        conn,
        "SELECT p.slug AS slug, ps.payload AS payload "
        "FROM projects p "
        "LEFT JOIN project_structure ps "
        "  ON ps.project_id = p.id "
        "  AND ps.family IN ('command_definitions', 'merge_verification') "
        "ORDER BY p.slug",
    )
    configured: Dict[str, bool] = {}
    for row in rows:
        slug = str(row["slug"])
        configured.setdefault(slug, False)
        if _payload_has_command(row["payload"]):
            configured[slug] = True

    inert = sorted(slug for slug, ok in configured.items() if not ok)
    if not inert:
        rec.record(
            CHECK_ID, CHECK_NAME, "PASS",
            "Every project has a test command or merge-verification policy.",
        )
        return

    detail = (
        "Projects with NO test command and NO merge-verification policy: "
        f"{', '.join(inert)}.\n"
        "  Their merge gate runs zero tests (the merge engine reads only "
        "merge_verification and never falls back to a full command), and "
        "tester / advance / polish have no project test command.\n"
        "  Seed the project's structure by running the onboard-project skill "
        "for it (it configures command_definitions and merge_verification)."
    )
    rec.record(CHECK_ID, CHECK_NAME, "WARN", detail)


__all__ = [
    "CHECK_ID",
    "CHECK_NAME",
    "hc_project_verification_configured",
]
