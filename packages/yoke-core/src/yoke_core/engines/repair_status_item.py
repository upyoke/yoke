"""Item-status repair flow.

Owns lifecycle target-status validation and the item repair pipeline.
Imported by ``yoke_core.engines.repair_status`` as the canonical owner of
``_validate_item_target_status`` and ``repair_item_status``.
"""

from __future__ import annotations

import os
import sys

from yoke_core.domain import db_backend
from yoke_core.domain.workflow_runtime import WorkflowRuntime


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _validate_item_target_status(
    workflow: WorkflowRuntime,
    new_status: str,
) -> str | None:
    """Return a human-readable validation error, or None when valid."""
    if workflow.accepts_stage(new_status):
        return None
    declared = ", ".join(workflow.stage_ids)
    return (
        f"Error: {new_status!r} is not declared by "
        f"{workflow.workflow_id}@{workflow.version}. Stages: {declared} "
        "(plus blocked, stopped, failed, cancelled)."
    )


def repair_item_status(item_ref: str, new_status: str, *, dry_run: bool, reason: str) -> int:
    """Repair a backlog item's status through the canonical owner."""
    # Lazy import: the front door owns ``_connect`` and also imports this module
    # at top level. Importing at function-call time avoids the bidirectional
    # partial-load failure when a sibling is imported before the front door
    # (e.g. via a direct ``from yoke_core.engines.repair_status_item import ...``).
    from yoke_core.domain.project_identity import render_item_ref
    from yoke_core.domain.yok_n_parser import parse_item_argument
    from yoke_core.engines.repair_status import _connect

    with _connect() as conn:
        # Resolve the operator ref to the internal id through the canonical
        # parser: ``PREFIX-N`` maps to its project ``public_item_prefix`` +
        # ``project_sequence`` (not a stripped global id), while a bare number
        # uses the mapped checkout project.
        try:
            item_id = parse_item_argument(item_ref, conn=conn)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        p = _p(conn)
        row = conn.execute(
            f"SELECT id, status FROM items WHERE id = {p}",
            (item_id,),
        ).fetchone()
        if row is not None:
            from yoke_core.domain.workflow_runtime import (
                load_item_workflow_runtime,
            )

            workflow = load_item_workflow_runtime(conn, item_id)
        item_display = render_item_ref(conn, item_id)

    if row is None or not row["status"]:
        print(f"Error: Item {item_display} not found.", file=sys.stderr)
        return 3

    old_status = str(row["status"])
    error = _validate_item_target_status(workflow, new_status)
    if error is not None:
        print(error, file=sys.stderr)
        return 2

    if old_status == new_status:
        print(f"No change: {item_display} is already at '{new_status}'.")
        return 0

    if dry_run:
        print(
            f"[DRY-RUN] Would repair {item_display}: {old_status} -> {new_status} "
            f"(reason: {reason})"
        )
        return 0

    print(f"Repairing {item_display}: {old_status} -> {new_status} (reason: {reason})")

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

    # Best-effort body-to-GitHub sync. The sync addresses the item by its
    # public ref — a digit string is a project-local sequence, not items.id.
    try:
        from yoke_core.domain import backlog_github_sync

        rc = backlog_github_sync.sync_body(
            item_display, stdout=sys.stderr, stderr=sys.stderr
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(
            f"Warning: sync_body failed for {item_display}: {exc}",
            file=sys.stderr,
        )
    else:
        if rc != 0:
            print(
                f"Warning: sync_body returned {rc} for {item_display} — the "
                "status repair landed locally but the GitHub issue body still "
                "shows the old state. Re-run `/yoke resync --fix`.",
                file=sys.stderr,
            )

    print(f"Repaired: {item_display} {old_status} -> {new_status}")
    print(f"Event emitted: ItemStatusChanged (source: repair-status:{reason})")
    return 0
