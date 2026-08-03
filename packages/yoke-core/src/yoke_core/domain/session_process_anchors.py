"""Hook-written session process-anchor registry (machine-home-bound shim).

The portable ancestry walk and the registry read/write/prune body live in
:mod:`yoke_contracts.session_identity` so the engine core and the thin
product CLI client resolve identity through one implementation. This module
binds that shared body to the Yoke-core machine home — the only
core-specific input is :func:`anchors_dir` — and preserves the
``yoke_core.domain.session_process_anchors`` import surface that the hook
registrar and the ambient-identity chain depend on.

Storage: one small JSON file per anchor pid under
``<machine-home>/session-anchors/`` (atomic tmp+rename writes, no locking).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

from yoke_contracts import session_identity
from yoke_contracts.session_identity import ANCHORS_DIR_NAME
from yoke_core.domain import machine_config


def anchors_dir() -> Path:
    """Return the machine-home session-anchor registry directory."""
    return machine_config.yoke_home() / ANCHORS_DIR_NAME


def _liveness_probe() -> Optional[session_identity.ContenderIsLive]:
    """The transport-backed session liveness probe, or ``None`` unavailable."""
    try:
        from yoke_cli.transport.session_liveness import contender_is_live
    except Exception:  # noqa: BLE001 — no probe degrades to fail-closed
        return None
    return contender_is_live


def _emit_contention_observed(
    record: Dict[str, Any], writer_session_id: str,
) -> None:
    """Ledger visibility for a contended anchor write. Never raises."""
    try:
        from yoke_core.domain.events import emit_event

        emit_event(
            "SessionAnchorContentionObserved",
            event_kind="lifecycle",
            event_type="session_lifecycle",
            source_type="system",
            severity="WARN",
            outcome="observed",
            session_id=writer_session_id,
            context={
                "anchor_pid": record.get("anchor_pid"),
                "contending_session_ids": record.get(
                    "contending_session_ids", []
                ),
                "last_writer_pid": record.get("last_writer_pid"),
                "last_writer_argv": record.get("last_writer_argv", ""),
            },
        )
    except Exception:  # noqa: BLE001 — telemetry must not break the write
        return


def record_session_anchor(
    session_id: str,
    *,
    transcript_path: str = "",
    pid: Optional[int] = None,
    anchor: Optional[session_identity.ProcessAnchor] = None,
) -> Optional[Dict[str, Any]]:
    """Record the calling process's nearest harness ancestor for ``session_id``.

    Returns the written record, or ``None`` when no harness ancestor exists
    or the write failed. Never raises. ``anchor`` injects a resolved
    ancestor for tests. Contended tenancy re-verifies recorded contenders
    against session liveness so a marker heals once its co-tenants end; a
    write that stays contended is surfaced on the events ledger.
    """
    record = session_identity.record_session_anchor(
        session_id,
        anchors_dir(),
        transcript_path=transcript_path,
        pid=pid,
        anchor=anchor,
        contender_is_live=_liveness_probe(),
    )
    if record is not None and record.get("shared_by_multiple_sessions"):
        _emit_contention_observed(record, session_id)
    return record


def resolve_session_from_ancestry(
    pid: Optional[int] = None,
    *,
    start_time_of: Optional[Callable[[int], Optional[str]]] = None,
    parents: Optional[Dict[int, int]] = None,
    name_of: Optional[Callable[[int], Optional[str]]] = None,
) -> Optional[str]:
    """Resolve the ambient session id by walking this process's ancestry.

    Returns ``None`` when no live anchor covers this process — including
    when the walk reaches a multiplexed harness host, whose anchors cannot
    name one session. Never raises. ``start_time_of`` / ``parents`` /
    ``name_of`` inject process-table lookups for tests.
    """
    return session_identity.resolve_session_from_ancestry(
        anchors_dir(),
        pid,
        start_time_of=start_time_of,
        parents=parents,
        name_of=name_of,
    )


def prune_stale_anchors(
    *,
    start_time_of: Optional[Callable[[int], Optional[str]]] = None,
) -> int:
    """Best-effort sweep removing records whose pid died or was reused.

    Returns the number of records removed; never raises.
    """
    return session_identity.prune_stale_anchors(
        anchors_dir(), start_time_of=start_time_of,
    )


__all__ = [
    "ANCHORS_DIR_NAME",
    "anchors_dir",
    "prune_stale_anchors",
    "record_session_anchor",
    "resolve_session_from_ancestry",
]
