"""Where governed-migration rehearsal receipts live, for writer and reader.

A rehearsal receipt is evidence about a work item: it says this item's history
entry applied cleanly to the model's validation surface. It therefore lives on
the control plane that holds the item — the database ``yoke migration
rehearse`` already opens to read the item and hold its migration-territory
claim, and the database the ``implementing -> reviewing-implementation`` gate
is evaluated against. Both sides take that one connection, so the writer and
the reader cannot name different databases.

The model's own authoritative database is the wrong home for this evidence.
It is a database the item's project owns, often reachable only with that
project's credentials, and frequently one per environment: the server that
evaluates the gate cannot open it, and could not say which environment's copy
to read if it could. The authority is still fingerprinted by the rehearsal and
that fingerprint is recorded on the receipt, as provenance.

Receipts are keyed by ``project_id`` and ``model_name``, so every project's
models share the one ``migration_audit`` table without colliding.
"""

from __future__ import annotations

from functools import partial
from typing import Any, Callable, Tuple

from yoke_core.domain import db_backend

#: Audit states at or past a passing rehearsal. A row that went further has
#: plainly rehearsed.
SETTLED_STATES = frozenset(
    {"rehearsed", "backup_created", "live_applied", "live_verified", "completed"}
)


def receipt_writers(
    control_conn: Any,
) -> Tuple[Callable[..., int], Callable[..., None]]:
    """Ensure the receipt table and return ``(insert_row, update_state)``.

    Both callables are bound to *control_conn* and use its native dialect.
    """
    if db_backend.connection_is_postgres(control_conn):
        from yoke_core.domain.migration_audit_schema import (
            ensure_migration_audit_table_postgres,
        )
        from yoke_core.domain.migration_harness_checks import (
            pg_insert_migration_audit_row,
            pg_update_migration_audit_state,
        )

        ensure_migration_audit_table_postgres(control_conn)
        return (
            partial(pg_insert_migration_audit_row, control_conn),
            partial(pg_update_migration_audit_state, control_conn),
        )
    from yoke_core.domain.migration_apply_audit import (
        _insert_audit_row,
        _update_audit_state,
    )
    from yoke_core.domain.migration_audit_schema import ensure_migration_audit_table

    ensure_migration_audit_table(control_conn)
    return (
        partial(_insert_audit_row, control_conn),
        partial(_update_audit_state, control_conn),
    )


def module_rehearsed(
    control_conn: Any, *, project_id: int, model_name: str, identifier: str
) -> bool:
    """True when this control plane holds a passing receipt for *identifier*.

    Rehearsal is the evidence a work item can produce before it merges.
    Applying is the boot converge's job after the item lands, so a completed
    apply cannot be demanded here.
    """
    p = "%s" if db_backend.connection_is_postgres(control_conn) else "?"
    try:
        rows = control_conn.execute(
            "SELECT state FROM migration_audit "
            f"WHERE migration_name = {p} AND project_id = {p} "
            f"AND COALESCE(model_name, {p}) = {p}",
            (identifier, int(project_id), model_name, model_name),
        ).fetchall()
    except db_backend.operational_error_types(control_conn):
        # No receipt table on this control plane means no receipt was ever
        # written here; the rehearsal creates it.
        if db_backend.connection_is_postgres(control_conn):
            control_conn.rollback()
        return False
    for row in rows:
        state = row["state"] if hasattr(row, "keys") else row[0]
        if state and str(state) in SETTLED_STATES:
            return True
    return False


__all__ = ["SETTLED_STATES", "module_rehearsed", "receipt_writers"]
