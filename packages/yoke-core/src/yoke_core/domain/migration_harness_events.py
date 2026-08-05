"""Durable event emission for governed migration harness flows."""

from __future__ import annotations

import sqlite3
from typing import Any, Dict

from yoke_core.domain.migration_harness_contract import AuditEmissionError

def _emit_event(
    db_path: str, event_name: str, detail: Dict[str, Any],
    severity: str = "CRITICAL",
) -> None:
    """Emit a migration event via the native Python emitter.

    Uses an explicit ``db_path`` override so migration telemetry lands in the
    pre-migration DB (not the caller's default YOKE_DB).
    """
    from yoke_core.domain.events import emit_event as _native_emit

    # This compatibility harness owns an explicit SQLite validation/archive
    # file. Pass a connection, not just its path: ambient Postgres authority
    # deliberately wins in the generic backend resolver and would otherwise
    # redirect the supposedly file-local evidence to another database.
    with sqlite3.connect(db_path) as conn:
        result = _native_emit(
            event_name,
            event_kind="system",
            event_type="system",
            # The harness is an executable migration script. Keep this value
            # in the event schema's closed source-type vocabulary rather than
            # inventing a tool-specific type that the writer rejects.
            source_type="script",
            severity=severity,
            outcome="completed",
            context={"detail": detail},
            conn=conn,
        )
    if not result.ok:
        raise AuditEmissionError(
            f"could not persist {event_name} migration event: {result.reason}"
        )
