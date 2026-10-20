"""The setup handoff row, read from the project's latest snapshot sync.

Setup blocks the ``setup-checklist-handoff`` row when its snapshot sync did
not land, and names ``yoke project snapshot sync`` as the repair. That repair
must clear the row: a successful sync records the row configured again, so a
checklist never keeps a blocker its own recovery already removed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping, TextIO

from yoke_contracts.onboard_checklist import (
    SETUP_HANDOFF_ROW_ID,
    STATUS_BLOCKED,
    STATUS_CONFIGURED,
)

DEFAULT_REPAIR = "yoke project snapshot sync"


def row_update(
    snapshot_sync: Mapping[str, Any] | None,
) -> tuple[str, dict[str, Any], str | None]:
    """Return the handoff row's ``(status, evidence, blocker)`` for a sync."""
    snapshot = dict(snapshot_sync or {})
    evidence = {"snapshot_sync": snapshot}
    if snapshot.get("status") == "ok":
        return STATUS_CONFIGURED, evidence, None
    repair = snapshot.get("repair_command") or DEFAULT_REPAIR
    return STATUS_BLOCKED, evidence, f"Run `{repair}` before path-claim flows."


def clear_blocked_row(
    project: str | None,
    *,
    config_path: str | Path | None = None,
    stderr: TextIO | None = None,
) -> bool:
    """After a successful sync, record a blocked handoff row configured.

    Returns whether a row was cleared. A failure here leaves the sync itself
    intact and says so where the operator reads the sync's own output.
    """
    if not project:
        return False
    stderr = stderr or sys.stderr
    from yoke_cli.config.project_onboard_support import dispatch

    try:
        found = dispatch("onboard.checklist.get", {"project": project}, config_path)
        run = found.get("run") or {}
        row = next(
            (
                row
                for row in run.get("rows") or []
                if row.get("row_id") == SETUP_HANDOFF_ROW_ID
            ),
            None,
        )
        if row is None or row.get("status") != STATUS_BLOCKED:
            return False
        status, evidence, blocker = row_update(
            {"attempted": True, "status": "ok", "source": DEFAULT_REPAIR}
        )
        dispatch(
            "onboard.checklist.run",
            {
                "run_id": run["run_id"],
                "project": project,
                "row_status": {SETUP_HANDOFF_ROW_ID: status},
                "evidence": {SETUP_HANDOFF_ROW_ID: evidence},
                "blocker": {SETUP_HANDOFF_ROW_ID: blocker},
            },
            config_path,
        )
    except Exception as exc:  # noqa: BLE001 - the sync already succeeded
        print(
            "warning: setup_handoff_row_not_cleared: the snapshot synced, but "
            f"the setup checklist still shows {SETUP_HANDOFF_ROW_ID} blocked: "
            f"{exc}. recipe: re-run `{DEFAULT_REPAIR} --project {project}`, "
            f"then `yoke onboard checklist get --project {project}`",
            file=stderr,
        )
        return False
    print(f"setup checklist: {SETUP_HANDOFF_ROW_ID} configured", file=stderr)
    return True


__all__ = ["DEFAULT_REPAIR", "clear_blocked_row", "row_update"]
