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

from yoke_cli.config import machine_config
from yoke_contracts.session_identity import (
    ANCHORS_DIR_NAME,
    prune_stale_anchors,
    record_session_anchor as _record_session_anchor,
)


def _anchors_dir():
    return machine_config.yoke_home() / ANCHORS_DIR_NAME


def record_session_anchor(session_id: str, *, transcript_path: str = "") -> None:
    """Best-effort product-side session anchor write."""
    _record_session_anchor(
        session_id, _anchors_dir(), transcript_path=transcript_path,
    )


def prune_stale_session_anchors() -> None:
    """Best-effort cleanup for the client-side registry at session start."""
    try:
        prune_stale_anchors(_anchors_dir())
    except Exception:
        return


__all__ = ["prune_stale_session_anchors", "record_session_anchor"]
