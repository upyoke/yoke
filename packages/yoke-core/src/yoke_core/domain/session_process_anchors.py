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
    ancestor for tests.
    """
    return session_identity.record_session_anchor(
        session_id,
        anchors_dir(),
        transcript_path=transcript_path,
        pid=pid,
        anchor=anchor,
    )


def resolve_session_from_ancestry(
    pid: Optional[int] = None,
    *,
    start_time_of: Optional[Callable[[int], Optional[str]]] = None,
    parents: Optional[Dict[int, int]] = None,
) -> Optional[str]:
    """Resolve the ambient session id by walking this process's ancestry.

    Returns ``None`` when no live anchor covers this process. Never raises.
    ``start_time_of`` / ``parents`` inject process-table lookups for tests.
    """
    return session_identity.resolve_session_from_ancestry(
        anchors_dir(), pid, start_time_of=start_time_of, parents=parents,
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
