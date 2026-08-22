"""Doctor validation for organization-wide fleet settings documents."""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.organization_contract.fleet_keys import (
    FleetSettingsError,
    validate_fleet_settings,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


HC_SLUG = "HC-organization-settings"
HC_LABEL = "Organization settings match the closed fleet-key registry"


def hc_organization_settings(
    conn: Any,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    del args
    if not _table_exists(conn, "organizations") or not _column_exists(
        conn,
        "organizations",
        "settings",
    ):
        rec.record(
            HC_SLUG,
            HC_LABEL,
            "SKIP",
            "organizations.settings is not present on this schema",
        )
        return
    findings: list[str] = []
    for row in conn.execute(
        "SELECT id, slug, settings FROM organizations ORDER BY id"
    ).fetchall():
        try:
            document = json.loads(str(row[2] or "{}"))
            if not isinstance(document, dict):
                raise FleetSettingsError("settings root must be an object")
            validate_fleet_settings(document)
        except (TypeError, ValueError, FleetSettingsError) as exc:
            findings.append(f"org={row[1]!r} id={row[0]}: {exc}")
    if findings:
        rec.record(
            HC_SLUG,
            HC_LABEL,
            "FAIL",
            "Invalid organization settings:\n" + "\n".join(findings[:20]),
        )
        return
    rec.record(
        HC_SLUG,
        HC_LABEL,
        "PASS",
        "Every organization settings document contains only valid registry keys.",
    )


__all__ = ["HC_LABEL", "HC_SLUG", "hc_organization_settings"]
