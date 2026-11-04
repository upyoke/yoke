"""Refuse retirement while live workflow state still requires the removed gate."""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _column_exists, _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE
RETIRED_GATE_ID = "db_claim_prose"
_ENGINE_TERMINAL_STAGE_IDS = frozenset({"cancelled", "stopped"})


def _definition(raw: Any) -> dict:
    return raw if isinstance(raw, dict) else json.loads(str(raw or "{}"))


def _names_retired_gate(definition: dict) -> bool:
    return any(
        gate.get("id") == RETIRED_GATE_ID
        for stage in definition.get("stages", ())
        for gate in stage.get("gates", ())
    )


def _pinned_items(conn: Any) -> list[str]:
    if not (
        _table_exists(conn, "items")
        and _table_exists(conn, "workflow_versions")
        and _column_exists(conn, "items", "workflow_version_id")
    ):
        return []
    has_prefix = _table_exists(conn, "projects") and _column_exists(
        conn, "projects", "public_item_prefix"
    )
    prefix = "p.public_item_prefix" if has_prefix else "NULL"
    sequence = (
        "i.project_sequence" if _column_exists(conn, "items", "project_sequence")
        else "NULL"
    )
    join = "LEFT JOIN projects p ON p.id = i.project_id " if has_prefix else ""
    rows = conn.execute(
        f"SELECT i.id, i.status, v.definition_json, {prefix}, {sequence}, "
        "v.workflow_id, v.version FROM items i "
        "JOIN workflow_versions v ON v.id = i.workflow_version_id "
        f"{join}ORDER BY i.id"
    ).fetchall()
    pinned = []
    for row in rows:
        definition = _definition(row[2])
        terminal = set(definition.get("terminal_stage_ids", ())) | _ENGINE_TERMINAL_STAGE_IDS
        if str(row[1]) in terminal or not _names_retired_gate(definition):
            continue
        label = f"{row[3]}-{row[4]}" if row[3] and row[4] is not None else f"item {row[0]}"
        pinned.append(
            f"{label} ({row[5]}@{row[6]}, {row[1]}): "
            f"`yoke workflows item migrate {label}`"
        )
    return pinned


def _current_versions(conn: Any) -> list[str]:
    if not (
        _table_exists(conn, "workflows")
        and _table_exists(conn, "workflow_versions")
        and _column_exists(conn, "workflows", "current_version_id")
    ):
        return []
    return [
        f"{row[0]}@{row[1]}"
        for row in conn.execute(
            "SELECT v.workflow_id, v.version, v.definition_json FROM workflows w "
            "JOIN workflow_versions v ON v.id = w.current_version_id "
            "ORDER BY v.workflow_id, v.version"
        ).fetchall()
        if _names_retired_gate(_definition(row[2]))
    ]


def _refuse_live_gate(conn: Any) -> None:
    pinned = _pinned_items(conn)
    current = _current_versions(conn)
    if not pinned and not current:
        return
    details = []
    if pinned:
        details.append("Non-terminal item pins: " + "; ".join(pinned) + ".")
    if current:
        details.append(
            "Current workflow versions: " + ", ".join(current)
            + "."
        )
    raise RuntimeError(compose_refusal(
        "retired_db_claim_prose_gate_pinned: " + " ".join(details),
        evaluated="Open item pins and current workflow versions; this entry changes no rows",
        recovery=(
            "On the build this universe is running now, select a version without "
            "the retired gate using `yoke workflows current set`, migrate the "
            "named items with their listed commands, then retry release or boot"
        ),
    ))


def apply(conn: Any) -> None:
    _refuse_live_gate(conn)


def invariants(conn: Any) -> None:
    _refuse_live_gate(conn)
