"""Task-status repair flow.

Owns the epic-task repair pipeline and TaskStatusChanged emission. Imported by
``yoke_core.engines.repair_status`` as the canonical owner of
``repair_task_status``.
"""

from __future__ import annotations

import os
import sys

from yoke_core.domain import db_backend
from yoke_core.domain.lifecycle import is_valid_task_status


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def repair_task_status(
    epic_ref: str,
    task_num_ref: str,
    new_status: str,
    *,
    dry_run: bool,
    reason: str,
) -> int:
    """Repair an epic task's status through the canonical owner."""
    # Lazy import: the front door owns the CLI infrastructure helpers and
    # also imports this module at top level. Importing at call time avoids
    # the bidirectional partial-load failure when this sibling is imported
    # before the front door.
    from yoke_core.engines.repair_status import (
        _connect,
        _normalize_ref,
        _normalize_task_num,
    )

    epic_id = _normalize_ref(epic_ref)
    if not epic_id:
        print("Error: epic ID is required.", file=sys.stderr)
        return 1
    try:
        task_num = _normalize_task_num(task_num_ref)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    with _connect() as conn:
        p = _p(conn)
        row = conn.execute(
            f"SELECT status FROM epic_tasks WHERE epic_id = {p} AND task_num = {p}",
            (epic_id, task_num),
        ).fetchone()

    if row is None or not row["status"]:
        print(f"Error: Task {epic_id}/{task_num} not found.", file=sys.stderr)
        return 3

    old_status = str(row["status"])
    if not is_valid_task_status(new_status):
        print(f"Error: '{new_status}' is not a valid task status.", file=sys.stderr)
        return 2

    if old_status == new_status:
        print(f"No change: Task {epic_id}/{task_num} is already at '{new_status}'.")
        return 0

    if dry_run:
        print(
            f"[DRY-RUN] Would repair task {epic_id}/{task_num}: {old_status} -> "
            f"{new_status} (reason: {reason})"
        )
        return 0

    print(
        f"Repairing task {epic_id}/{task_num}: {old_status} -> {new_status} "
        f"(reason: {reason})"
    )

    # Use the owned task-status domain so claim bypass and event semantics stay
    # aligned with normal lifecycle writes.
    from yoke_core.domain import db_helpers
    from yoke_core.domain.update_status import update_task_status

    env_overrides = {
        "YOKE_CLAIM_BYPASS": f"repair-status:{reason}",
        "YOKE_TASK_DONE_VERIFIED": "1",
    }
    previous_env: dict[str, str | None] = {}
    for key, val in env_overrides.items():
        previous_env[key] = os.environ.get(key)
        os.environ[key] = val
    try:
        with db_helpers.connect() as conn:
            update_rc = update_task_status(
                conn,
                str(epic_id),
                str(task_num),
                new_status,
                note=f"repair: {reason}",
                no_rebuild=False,
                no_github=False,
                no_derive=True,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
    finally:
        for key, prev in previous_env.items():
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev

    if update_rc != 0:
        return update_rc or 1

    # Emit via the native Python emitter. Non-fatal on failure.
    try:
        from yoke_core.domain.events import emit_event as _native_emit
        _envelope = _native_emit(
            "TaskStatusChanged",
            event_kind="lifecycle",
            event_type="task_status_change",
            source_type="system",
            severity="STATUS",
            outcome="completed",
            item_id=f"YOK-{epic_id}",
            task_num=int(task_num),
            context={
                "from_status": old_status,
                "to_status": new_status,
                "source": f"repair-status:{reason}",
            },
        )
        if not _envelope.ok:
            print("Warning: TaskStatusChanged event emission failed", file=sys.stderr)
    except Exception:
        print("Warning: TaskStatusChanged event emission failed", file=sys.stderr)

    print(f"Repaired: task {epic_id}/{task_num} {old_status} -> {new_status}")
    print(f"Event emitted: TaskStatusChanged (source: repair-status:{reason})")
    return 0
