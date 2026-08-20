"""``migration_audit`` receipts for the ordered migration history.

The ledger (``applied_migrations``) is the cursor and the authority on what a
database has run. A receipt is the *evidence* around that fact -- above all,
which restore point covers an apply, which is the hardest thing to reconstruct
at the moment anyone needs it.

Separate from the applier on purpose: applying is about ordering, locking and
the ledger, and must never fail over bookkeeping. Recording is about leaving a
trail. Keeping them apart is what lets the applier swallow a receipt failure
without that decision leaking into how receipts are written.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence, Set, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.migration_apply_attribution import (
    refuse_lane_as_model_name,
    require_attribution,
)
from yoke_core.domain.migration_history import MigrationEntry

DESCRIPTION = "boot-converge apply from the ordered migration history"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def now_stamp() -> str:
    """The timestamp format every migration row is written in."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_receipt(
    conn: Any,
    entry: MigrationEntry,
    *,
    state: str,
    started_at: str,
    completed_at: str,
    restore_point: str,
    attribution: Mapping[str, str],
    model_name: str,
    failure_reason: Optional[str] = None,
    project_id: Optional[int] = None,
) -> None:
    """Record one ``migration_audit`` row; never fail the caller over it.

    Attribution is required before this insert is attempted. A database
    error writing the row still does not fail the apply — evidence is not
    worth failing a boot — but missing session, actor, branch, or commit
    is a refused apply, not a bookkeeping miss.
    """
    fields = require_attribution(attribution)
    model = refuse_lane_as_model_name(model_name)
    p = _p(conn)
    try:
        conn.execute(
            "INSERT INTO migration_audit "
            "(migration_name, state, backup_path, failure_reason, "
            " started_at, completed_at, description, "
            " tables_declared, expected_deltas, pre_row_counts, "
            " project_id, model_name, session_id, actor_id, "
            " source_branch, source_commit) "
            f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, "
            f"{p}, {p}, {p}, {p}, {p}, {p})",
            (
                entry.name,
                state,
                restore_point,
                failure_reason,
                started_at,
                completed_at,
                DESCRIPTION,
                json.dumps([]),
                json.dumps({}),
                json.dumps({}),
                project_id,
                model,
                fields["session_id"],
                fields["actor_id"],
                fields["source_branch"],
                fields["source_commit"],
            ),
        )
        conn.commit()
    except Exception as exc:  # noqa: BLE001 — evidence is not worth failing a boot
        conn.rollback()
        # Loud, but not fatal. Swallowing this is right for a boot; hiding it
        # is not -- a silently lost receipt is first noticed while recovering
        # from something else, with no record of the covering restore point.
        print(
            f"WARNING: migration_audit receipt for {entry.name} "
            f"({state}) was not recorded: {exc}",
            file=sys.stderr,
        )


def record_missing_receipts(
    conn: Any,
    history: Sequence[MigrationEntry],
    *,
    applied: Set[str],
    stamp: str,
    restore_point: str,
    attribution: Mapping[str, str],
    model_name: str,
    project_id: Optional[int] = None,
) -> Tuple[str, ...]:
    """Write ``completed`` receipts for applied entries that have none.

    A receipt failure never fails an apply -- deliberately, since a boot must
    not die over evidence -- so "in the ledger, absent from ``migration_audit``"
    is a state this design can reach. Healing it belongs here rather than in
    whatever hand-written SQL an operator reaches for at the time.

    *applied* is the ledger, and it is what authorizes a receipt: an entry that
    never ran never gets one. *restore_point*, model, and attribution are
    facts the caller still holds; they are passed in rather than guessed.
    Existing unaudited rows are not rewritten.
    """
    p = _p(conn)
    if project_id is None:
        rows = conn.execute("SELECT migration_name FROM migration_audit").fetchall()
    else:
        # Evidence readers filter on project. A receipt carrying no project is
        # not evidence *for* one, so it does not count as already recorded.
        rows = conn.execute(
            f"SELECT migration_name FROM migration_audit WHERE project_id = {p}",
            (project_id,),
        ).fetchall()
    recorded = {str(row[0]) for row in rows}
    healed = [e for e in history if e.name in applied and e.name not in recorded]
    for entry in healed:
        write_receipt(
            conn,
            entry,
            state="completed",
            started_at=stamp,
            completed_at=stamp,
            restore_point=restore_point,
            project_id=project_id,
            model_name=model_name,
            attribution=attribution,
        )
    return tuple(e.name for e in healed)


__all__ = [
    "DESCRIPTION",
    "now_stamp",
    "record_missing_receipts",
    "write_receipt",
]
