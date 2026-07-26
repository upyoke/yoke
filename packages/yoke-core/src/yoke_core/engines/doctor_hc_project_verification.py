"""Doctor health check — every project can execute a QA plan."""

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
CHECK_NAME = "Project has an executable Command plan"


def _payload_has_command(payload_text) -> bool:
    """True when a structure payload carries a non-empty ``command`` string.

    Command cases store ``{"command": <str>}`` in ``method_config``.
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
        and _table_exists(conn, "qa_plans")
        and _table_exists(conn, "qa_plan_cases")
    ):
        return

    rows = query_rows(
        conn,
        "SELECT p.slug AS slug, c.method_config AS payload "
        "FROM projects p "
        "LEFT JOIN qa_plans qp "
        "  ON qp.project_id=p.id AND qp.retired_at IS NULL "
        "LEFT JOIN qa_plan_cases c "
        "  ON c.plan_id=qp.id AND c.method_id='command' "
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
            "Every project has at least one executable Command-plan case.",
        )
        return

    detail = (
        "Projects with NO executable Command-plan case: "
        f"{', '.join(inert)}.\n"
        "  Author and attach a project QA plan containing a Command case."
    )
    rec.record(CHECK_ID, CHECK_NAME, "WARN", detail)


__all__ = [
    "CHECK_ID",
    "CHECK_NAME",
    "hc_project_verification_configured",
]
