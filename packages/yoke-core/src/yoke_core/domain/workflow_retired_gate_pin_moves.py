"""Move eligible open canon pins after built-in workflow convergence."""

from __future__ import annotations

import json
import logging
from typing import Any

from yoke_core.domain.builtin_workflow_canon import recognize
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.workflow_item_versioning import migrate_item_workflow_pin
from yoke_core.domain.workflow_runtime import ENGINE_TERMINAL_STAGE_IDS

_LOG = logging.getLogger(__name__)
_WORKFLOWS = frozenset({"issue", "epic", "blitz", "dash"})


def _names_old_gate(definition: dict) -> bool:
    return any(
        gate["id"] == "db_claim_prose"
        for stage in definition["stages"] for gate in stage.get("gates", ())
    )


def move_open_items_off_retired_gate_versions(conn: Any) -> None:
    """Move each compatible item independently; refusals never fail boot.

    The current version must already omit the old gate. Universe-edited pins
    and terminal items stay untouched. Each migration locks and re-reads its
    item and commits or rolls back alone, including when live claims exist.
    """
    if not all(_table_exists(conn, table) for table in ("items", "workflows", "workflow_versions")):
        return
    try:
        rows = conn.execute(
            "SELECT i.id, i.status, v.workflow_id, v.definition_json, "
            "v.definition_digest, c.definition_json AS current_definition, "
            "c.version AS target_version FROM items i "
            "JOIN workflow_versions v ON v.id = i.workflow_version_id "
            "JOIN workflows w ON w.id = v.workflow_id "
            "JOIN workflow_versions c ON c.id = w.current_version_id"
        ).fetchall()
        for raw in rows:
            row = dict(raw)
            definition = json.loads(row["definition_json"])
            current = json.loads(row["current_definition"])
            terminal = set(definition["terminal_stage_ids"]) | ENGINE_TERMINAL_STAGE_IDS
            if (
                row["workflow_id"] not in _WORKFLOWS
                or row["status"] in terminal
                or not _names_old_gate(definition)
                or _names_old_gate(current)
                or recognize(row["workflow_id"], row["definition_digest"]) is None
            ):
                continue
            try:
                migrate_item_workflow_pin(
                    conn, item_id=int(row["id"]), target_version=int(row["target_version"]),
                )
            except Exception as exc:  # noqa: BLE001 - one refused pin must not stop boot
                conn.rollback()
                _LOG.warning(
                    "retired_gate_pin_move_refused: item_id=%s: %s; "
                    "inspect the item's pin and run `yoke workflows item migrate <item-ref>`",
                    row["id"], exc,
                )
    except Exception:  # noqa: BLE001 - availability wins over automatic rebinding
        conn.rollback()
        _LOG.exception(
            "retired_gate_pin_moves_unavailable: inspect workflow pins and retry boot"
        )
