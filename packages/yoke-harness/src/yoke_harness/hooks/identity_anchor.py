"""Best-effort product-side session anchor writes.

Binds the shared anchor-registry body in
:mod:`yoke_contracts.session_identity` to the product CLI's machine home.
The registry read side (``resolve_session_from_ancestry``) walks the parent
chain looking for a *per-session* harness process, so the write side must
resolve the same kind of ancestor: recording an arbitrary ``os.getppid()``
would key the record on whatever process happens to be the direct parent —
under a harness that hosts every conversation in one process, that is the
shared host, and each sibling session would then resolve to whichever one
wrote the record last.
"""

from __future__ import annotations

from typing import Optional

from yoke_cli.config import machine_config
from yoke_contracts.session_identity import (
    ANCHORS_DIR_NAME,
    ContenderIsLive,
    prune_stale_anchors,
    record_session_anchor as _record_session_anchor,
)
from yoke_contracts.process_ancestry import find_nearest_named_process_anchor
from yoke_contracts.session_control import liveness_process_names


def _anchors_dir():
    return machine_config.yoke_home() / ANCHORS_DIR_NAME


def _liveness_probe() -> Optional[ContenderIsLive]:
    """The transport-backed liveness probe so contention markers can heal."""
    try:
        from yoke_cli.transport.session_liveness import contender_is_live
    except Exception:  # noqa: BLE001 — no probe degrades to fail-closed
        return None
    return contender_is_live


def record_session_anchor(session_id: str, *, transcript_path: str = "") -> None:
    """Best-effort product-side session anchor write."""
    from yoke_harness.hooks.identity_runtime import (
        cursor_surface_entrypoint,
        detect_executor,
    )

    executor = detect_executor()
    surface = cursor_surface_entrypoint() if executor == "cursor" else executor
    names = liveness_process_names(surface)
    anchor = find_nearest_named_process_anchor(names) if names else None
    _record_session_anchor(
        session_id,
        _anchors_dir(),
        transcript_path=transcript_path,
        anchor=anchor,
        contender_is_live=_liveness_probe(),
    )


def prune_stale_session_anchors() -> None:
    """Best-effort cleanup for the client-side registry at session start."""
    try:
        prune_stale_anchors(_anchors_dir())
    except Exception:
        return


__all__ = ["prune_stale_session_anchors", "record_session_anchor"]
