"""Best-effort event emission for governed migration harness flows."""

from __future__ import annotations

from typing import Any, Dict

def _emit_event(
    db_path: str, event_name: str, detail: Dict[str, Any],
    severity: str = "CRITICAL",
) -> None:
    """Emit a migration event via the native Python emitter.

    Uses an explicit ``db_path`` override so migration telemetry lands in the
    pre-migration DB (not the caller's default YOKE_DB).
    """
    try:
        from yoke_core.domain.events import emit_event as _native_emit
        _native_emit(
            event_name,
            event_kind="system",
            event_type="system",
            source_type="migration_harness",
            severity=severity,
            outcome="completed",
            context={"detail": detail},
            db_path=db_path,
        )
    except Exception:
        pass  # Best-effort
