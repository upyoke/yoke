"""Item-status repair flow.

Owns lifecycle target-status validation and the item repair pipeline.
Imported by ``yoke_core.engines.repair_status`` as the canonical owner of
``_validate_item_target_status`` and ``repair_item_status``.
"""

from __future__ import annotations

import os
import sys

from yoke_core.domain import db_backend
from yoke_core.domain.lifecycle import (
    is_valid_epic_status,
    is_valid_issue_status,
    is_valid_item_status,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _validate_item_target_status(item_type: str, new_status: str) -> str | None:
    """Return a human-readable validation error, or None when valid."""
    if item_type == "issue":
        if is_valid_issue_status(new_status):
            return None
        return (
            f"Error: '{new_status}' is not a valid issue status. Issue items use "
            "the issue-workflow-type lifecycle: idea, refining-idea, refined-idea, "
            "implementing, reviewing-implementation, reviewed-implementation, "
            "polishing-implementation, implemented, release, done (plus blocked, "
            "stopped, failed, cancelled)."
        )
    if item_type == "epic":
        if is_valid_epic_status(new_status):
            return None
        return (
            f"Error: '{new_status}' is not a valid epic status. Epic items use "
            "the epic-workflow-type lifecycle: idea, refining-idea, refined-idea, "
            "planning, plan-drafted, refining-plan, planned, implementing, "
            "reviewing-implementation, reviewed-implementation, "
            "polishing-implementation, implemented, release, done (plus blocked, "
            "stopped, failed, cancelled)."
        )
    if is_valid_item_status(new_status):
        return None
    return f"Error: '{new_status}' is not a valid item status."


def repair_item_status(item_ref: str, new_status: str, *, dry_run: bool, reason: str) -> int:
    """Repair a backlog item's status through the canonical owner."""
    # Lazy import: the front door owns ``_connect`` / ``_normalize_item_id`` and
    # also imports this module at top level. Importing them at function-call
    # time avoids the bidirectional partial-load failure when a sibling is
    # imported before the front door (e.g. via a direct ``from
    # yoke_core.engines.repair_status_item import ...``).
    from yoke_core.engines.repair_status import _connect, _normalize_item_id

    try:
        item_id = _normalize_item_id(item_ref)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    with _connect() as conn:
        p = _p(conn)
        row = conn.execute(
            f"SELECT id, type, status FROM items WHERE id = {p}",
            (item_id,),
        ).fetchone()

    if row is None or not row["status"]:
        print(f"Error: Item YOK-{item_id} not found.", file=sys.stderr)
        return 3

    old_status = str(row["status"])
    item_type = str(row["type"] or "issue")
    error = _validate_item_target_status(item_type, new_status)
    if error is not None:
        print(error, file=sys.stderr)
        return 2

    if old_status == new_status:
        print(f"No change: YOK-{item_id} is already at '{new_status}'.")
        return 0

    if dry_run:
        print(
            f"[DRY-RUN] Would repair YOK-{item_id}: {old_status} -> {new_status} "
            f"(reason: {reason})"
        )
        return 0

    print(f"Repairing YOK-{item_id}: {old_status} -> {new_status} (reason: {reason})")

    # Repair is a sanctioned status write; assert done_nonce_verified when
    # targeting 'done'.
    from yoke_core.domain import backlog as _backlog

    env_overrides = {
        "YOKE_STATUS_SOURCE": f"repair-status:{reason}",
        "YOKE_CLAIM_BYPASS": f"repair-status:{reason}",
    }
    previous_env: dict[str, str | None] = {}
    for key, val in env_overrides.items():
        previous_env[key] = os.environ.get(key)
        os.environ[key] = val
    try:
        result = _backlog.execute_update(
            item_id=item_id,
            field="status",
            value=new_status,
            done_nonce_verified=(new_status == "done"),
            qa_bypass=os.environ.get("YOKE_QA_GATE_BYPASS", "0") == "1",
            rebuild_board=True,
            out=sys.stdout,
        )
    finally:
        for key, prev in previous_env.items():
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev

    if not result.get("success"):
        err = result.get("error") or "backlog update failed"
        print(f"Error: {err}", file=sys.stderr)
        return 1

    # Best-effort body-to-GitHub sync.
    try:
        from yoke_core.domain import backlog_github_sync

        backlog_github_sync.sync_body(
            str(item_id), stdout=sys.stderr, stderr=sys.stderr
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(
            f"Warning: sync_body failed for YOK-{item_id}: {exc}",
            file=sys.stderr,
        )

    print(f"Repaired: YOK-{item_id} {old_status} -> {new_status}")
    print(f"Event emitted: ItemStatusChanged (source: repair-status:{reason})")
    return 0
