"""Doctor health check for non-terminal items pinned to level-less versions.

A launch without an explicit ``--level`` resolves the item's live stage level
and refuses as ``stage_level_missing`` when the pinned workflow version does
not declare one. Existing pins never move automatically, so this check names
every non-terminal item whose pinned version leaves any non-terminal stage
without a level, together with the migrate recipe that moves it.
"""

from __future__ import annotations

import json
from typing import Any, List

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.workflow_runtime import ENGINE_TERMINAL_STAGE_IDS
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

CHECK_ID = "HC-workflow-stage-level-pins"
CHECK_NAME = "Non-terminal items pinned to level-less workflow versions"


def _definition(raw: Any) -> dict[str, Any]:
    return json.loads(raw) if isinstance(raw, str) else dict(raw or {})


def _terminal_stage_ids(definition: dict[str, Any]) -> set[str]:
    """Declared terminal stages plus the engine-owned exits every version shares."""
    declared = {str(value) for value in definition.get("terminal_stage_ids") or ()}
    return declared | ENGINE_TERMINAL_STAGE_IDS


def levelless_stage_ids(definition: dict[str, Any]) -> list[str]:
    """Non-terminal stages that declare no launch level."""
    terminal = _terminal_stage_ids(definition)
    return [
        str(stage["id"])
        for stage in definition.get("stages") or ()
        if str(stage.get("id")) not in terminal and not stage.get("level")
    ]


def _recovery(ref: str, current: Any) -> str:
    if current["version"] is None or levelless_stage_ids(
        _definition(current["definition_json"])
    ):
        return (
            "the workflow's current version is not levelled either: publish a "
            "version whose every non-terminal stage declares a level, then "
            f"`yoke workflows item migrate {ref} --version N --preview` and apply"
        )
    version = int(current["version"])
    return (
        f"`yoke workflows item migrate {ref} --version {version} --preview`, then "
        f"`yoke workflows item migrate {ref} --version {version}` "
        "(operator-started session)"
    )


def hc_workflow_stage_level_pins(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """FAIL naming each non-terminal item whose pinned version lacks levels."""
    rows = query_rows(
        conn,
        "SELECT i.id, i.status, i.workflow_id, v.version, v.definition_json, "
        "cv.version AS current_version, "
        "cv.definition_json AS current_definition_json "
        "FROM items i "
        "JOIN workflow_versions v ON v.id = i.workflow_version_id "
        "LEFT JOIN workflows w ON w.id = i.workflow_id "
        "LEFT JOIN workflow_versions cv ON cv.id = w.current_version_id "
        "ORDER BY i.id",
    )
    findings: List[str] = []
    for row in rows:
        definition = _definition(row["definition_json"])
        if str(row["status"]) in _terminal_stage_ids(definition):
            continue
        missing = levelless_stage_ids(definition)
        if not missing:
            continue
        ref = render_item_ref(conn, int(row["id"]))
        current = {
            "version": row["current_version"],
            "definition_json": row["current_definition_json"],
        }
        findings.append(
            f"- {ref} ({row['status']}): pinned to {row['workflow_id']} "
            f"v{row['version']}, whose stages {', '.join(missing)} declare no "
            "level, so a launch without --level refuses as "
            f"stage_level_missing. Recovery: {_recovery(ref, current)}"
        )
    if findings:
        rec.record(CHECK_ID, CHECK_NAME, "FAIL", "\n".join(findings))
    else:
        rec.record(CHECK_ID, CHECK_NAME, "PASS", "")


__all__ = ["hc_workflow_stage_level_pins", "levelless_stage_ids"]
