"""Controlled, audited repair surface for path-integrity findings.

Each repair operation reconciles a piece of substrate truth that the
verifier already flagged. Repairs cannot fabricate or rebind
path-target identity, never run scheduler logic, and never modify any
table outside the path substrate.

Lifecycle: a repair row is written in ``status='preparing'``
BEFORE substrate mutation, transitions to ``applied`` on success (with
an emitted ``PathIntegrityRepairApplied`` event) or ``failed`` on
exception. Repairs are idempotent. The operator-only
``mark_failure_abandoned`` flow flips a failure to
``repair_status='abandoned'`` with a recorded reason, no substrate
mutation.

Operations vocabulary:

* ``delete_duplicate_target`` — for ``duplicate_identity`` failures.
* ``rebind_parent`` — for ``parent_child_coherence`` failures.

Audit-row writers live in
:mod:`yoke_core.domain.path_integrity_repair_audit`.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.events import emit_event
from yoke_core.domain.path_integrity_repair_audit import (
    FAILURE_ABANDONED,
    FAILURE_OPEN,
    FAILURE_REPAIRED,
    STATUS_ABANDONED,
    STATUS_APPLIED,
    STATUS_FAILED,
    STATUS_PREPARING,
    close_repair_row,
    fetch_failure_row,
    fetch_project_for_run,
    mark_failure_repaired,
    open_repair_row,
    write_abandon_row,
)


OP_DELETE_DUPLICATE_TARGET = "delete_duplicate_target"
OP_REBIND_PARENT = "rebind_parent"


class PathIntegrityRepairError(Exception):
    """Raised when a repair refuses to apply."""


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _emit_repair_applied(
    conn: Any,
    *,
    project_id: str,
    failure_id: int,
    repair_id: int,
    operation: str,
    arguments: dict,
) -> Optional[str]:
    envelope = emit_event(
        "PathIntegrityRepairApplied",
        event_kind="lifecycle",
        event_type="path_integrity",
        source_type="backend",
        project=project_id,
        outcome="completed",
        context={
            "project_id": project_id,
            "failure_id": failure_id,
            "repair_id": repair_id,
            "operation": operation,
            "arguments": arguments,
        },
        conn=conn,
    )
    if not envelope.ok:
        return None
    return str(envelope.get("event_id"))


def _apply_delete_duplicate_target(
    conn: Any, target_id: int
) -> None:
    p = _p(conn)
    conn.execute(
        f"DELETE FROM path_snapshot_entries WHERE target_id={p}",
        (target_id,),
    )
    # Detach the row from any failure audit references before delete
    # so FK enforcement on path_integrity_failures.target_id does not
    # block. The audit row stays as a fact (target_id becomes NULL).
    conn.execute(
        "UPDATE path_integrity_failures "
        f"SET target_id = NULL WHERE target_id = {p}",
        (target_id,),
    )
    conn.execute(
        f"DELETE FROM path_targets WHERE id={p}", (target_id,),
    )


def _apply_rebind_parent(
    conn: Any,
    target_id: int,
    project_id: str,
) -> None:
    p = _p(conn)
    row = conn.execute(
        "SELECT id FROM path_targets "
        f"WHERE project_id={p} AND path_string={p} "
        "ORDER BY generation DESC LIMIT 1",
        (project_id, ""),
    ).fetchone()
    if row is None:
        raise PathIntegrityRepairError(
            f"project {project_id!r} has no root path_target to "
            "rebind onto"
        )
    in_project_root = int(row[0])
    conn.execute(
        f"UPDATE path_targets SET parent_target_id={p} WHERE id={p}",
        (in_project_root, target_id),
    )


_DEFAULT_OPS = {
    "duplicate_identity": OP_DELETE_DUPLICATE_TARGET,
    "parent_child_coherence": OP_REBIND_PARENT,
}


def _default_operation(invariant_kind: str) -> Optional[str]:
    return _DEFAULT_OPS.get(invariant_kind)


def apply_repair(
    conn: Any,
    *,
    failure_id: int,
    operation: Optional[str] = None,
    dry_run: bool = False,
) -> int:
    """Apply a sanctioned repair for ``failure_id``.

    Returns the ``path_integrity_repairs.id``. When ``dry_run`` is True
    the repair row is opened in ``preparing`` and immediately closed
    to ``applied`` without substrate mutation; the caller can inspect
    the row to confirm the planned change.
    """
    failure = fetch_failure_row(conn, failure_id)
    if failure is None:
        raise PathIntegrityRepairError(
            f"path_integrity_failures row {failure_id} not found"
        )
    invariant_kind = str(failure[2])
    target_id = failure[3]
    repair_status = str(failure[4])
    if repair_status == FAILURE_REPAIRED:
        p = _p(conn)
        row = conn.execute(
            "SELECT id FROM path_integrity_repairs "
            f"WHERE failure_id={p} AND status={p} "
            "ORDER BY id DESC LIMIT 1",
            (failure_id, STATUS_APPLIED),
        ).fetchone()
        if row is not None:
            return int(row[0])
        raise PathIntegrityRepairError(
            f"failure {failure_id} is marked repaired but has no "
            "applied repair audit row"
        )

    op = operation or _default_operation(invariant_kind)
    if op is None:
        raise PathIntegrityRepairError(
            f"no default repair operation for invariant "
            f"{invariant_kind!r}; pass --operation explicitly"
        )

    arguments = {
        "operation": op,
        "target_id": target_id,
        "invariant_kind": invariant_kind,
        "dry_run": dry_run,
    }
    repair_id = open_repair_row(
        conn, failure_id=failure_id, operation=op, arguments=arguments,
    )

    if dry_run:
        close_repair_row(
            conn, repair_id=repair_id, status=STATUS_APPLIED,
        )
        return repair_id

    project_id = fetch_project_for_run(conn, int(failure[1]))
    if project_id is None:
        close_repair_row(
            conn, repair_id=repair_id, status=STATUS_FAILED,
            error_text=f"path_integrity_runs row {failure[1]} not found",
        )
        raise PathIntegrityRepairError(
            f"path_integrity_runs row {failure[1]} not found"
        )
    try:
        if op == OP_DELETE_DUPLICATE_TARGET:
            if target_id is None:
                raise PathIntegrityRepairError(
                    "delete_duplicate_target requires a target_id"
                )
            _apply_delete_duplicate_target(conn, int(target_id))
        elif op == OP_REBIND_PARENT:
            if target_id is None:
                raise PathIntegrityRepairError(
                    "rebind_parent requires a target_id"
                )
            _apply_rebind_parent(conn, int(target_id), project_id)
        else:
            raise PathIntegrityRepairError(
                f"unknown repair operation {op!r}"
            )
    except Exception as exc:
        close_repair_row(
            conn, repair_id=repair_id, status=STATUS_FAILED,
            error_text=str(exc),
        )
        raise

    conn.commit()
    event_id = _emit_repair_applied(
        conn, project_id=project_id, failure_id=failure_id,
        repair_id=repair_id, operation=op, arguments=arguments,
    )
    close_repair_row(
        conn, repair_id=repair_id, status=STATUS_APPLIED,
        recorded_event_id=event_id,
    )
    mark_failure_repaired(conn, failure_id)
    return repair_id


def mark_failure_abandoned(
    conn: Any,
    *,
    failure_id: int,
    reason: str,
) -> int:
    """Operator-only abandon transition.

    Records an ``abandoned`` ``path_integrity_repairs`` row with the
    supplied reason, flips the matching
    ``path_integrity_failures.repair_status`` to ``abandoned``, and
    decrements the run's ``unrepaired_failure_count``. No substrate is
    modified.
    """
    failure = fetch_failure_row(conn, failure_id)
    if failure is None:
        raise PathIntegrityRepairError(
            f"path_integrity_failures row {failure_id} not found"
        )
    if str(failure[4]) == FAILURE_REPAIRED:
        raise PathIntegrityRepairError(
            f"failure {failure_id} already marked repaired"
        )
    if not reason or not reason.strip():
        raise PathIntegrityRepairError(
            "abandon reason must be a non-empty string"
        )
    return write_abandon_row(
        conn, failure_id=failure_id, reason=reason,
    )


def main(argv=None) -> int:
    from yoke_core.domain.path_integrity_repair_cli import (
        main as _cli_main,
    )
    return _cli_main(argv)


__all__ = [
    "FAILURE_ABANDONED",
    "FAILURE_OPEN",
    "FAILURE_REPAIRED",
    "OP_DELETE_DUPLICATE_TARGET",
    "OP_REBIND_PARENT",
    "PathIntegrityRepairError",
    "STATUS_ABANDONED",
    "STATUS_APPLIED",
    "STATUS_FAILED",
    "STATUS_PREPARING",
    "apply_repair",
    "main",
    "mark_failure_abandoned",
]


if __name__ == "__main__":
    raise SystemExit(main())
