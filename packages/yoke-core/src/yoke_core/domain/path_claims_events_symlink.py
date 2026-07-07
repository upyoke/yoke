"""Event emitters for symlink-aware path-claim registration.

Sibling of :mod:`yoke_core.domain.path_claims_events`. Carries the
two symlink-canonicalization event names so the parent events module
stays under its 350-line cap.

Required event names:

  PathTargetSymlinkCanonicalized  (INFO, lifecycle)
  PathTargetSymlinkSkipped        (INFO, lifecycle)

Both events ride on the same canonical emit path used by the rest of
the path-claim lifecycle. Payloads carry the symlink + canonical path
strings (or the raw readlink target for skips), the project id, and
the owning claim id so the doctor invariant and any audit reader can
reconstruct the equivalence class without re-walking the filesystem.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


_EVENT_KIND = "lifecycle"
_EVENT_TYPE = "path_claim"
_SOURCE_TYPE = "system"


def _resolve_session_id(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    for env_name in (
        "YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID",
    ):
        value = os.environ.get(env_name)
        if value:
            return value
    return ""


def _emit(
    *,
    name: str,
    severity: str,
    outcome: str,
    conn: Optional[Any],
    item_id: Optional[int],
    project: Optional[str],
    session_id: Optional[str],
    context: Dict[str, Any],
) -> Optional[str]:
    try:
        from yoke_core.domain.events import emit_event as _native_emit
    except ImportError:
        return None
    try:
        envelope = _native_emit(
            name,
            event_kind=_EVENT_KIND,
            event_type=_EVENT_TYPE,
            source_type=_SOURCE_TYPE,
            session_id=_resolve_session_id(session_id),
            severity=severity,
            outcome=outcome,
            project=project or "yoke",
            item_id=item_id,
            context=context,
            conn=conn,
        )
    except Exception:
        return None
    if envelope is None:
        return None
    return envelope.get("event_id")


def emit_symlink_canonicalized(
    *,
    conn: Optional[Any],
    claim_id: int,
    project: Optional[str],
    symlink_path: str,
    canonical_path: str,
    symlink_target_id: Optional[int],
    canonical_target_id: Optional[int],
    item_id: Optional[int] = None,
    session_id: Optional[str] = None,
) -> Optional[str]:
    return _emit(
        name="PathTargetSymlinkCanonicalized",
        severity="INFO",
        outcome="completed",
        conn=conn,
        item_id=item_id,
        project=project,
        session_id=session_id,
        context={
            "claim_id": claim_id,
            "symlink_path_string": symlink_path,
            "canonical_path_string": canonical_path,
            "symlink_target_id": symlink_target_id,
            "canonical_target_id": canonical_target_id,
        },
    )


def emit_symlink_skipped(
    *,
    conn: Optional[Any],
    claim_id: Optional[int],
    project: Optional[str],
    symlink_path: str,
    reason: str,
    target_attempt: Optional[str] = None,
    symlink_target_id: Optional[int] = None,
    item_id: Optional[int] = None,
    session_id: Optional[str] = None,
) -> Optional[str]:
    return _emit(
        name="PathTargetSymlinkSkipped",
        severity="INFO",
        outcome="completed",
        conn=conn,
        item_id=item_id,
        project=project,
        session_id=session_id,
        context={
            "claim_id": claim_id,
            "symlink_path_string": symlink_path,
            "reason": reason,
            "target_attempt": target_attempt,
            "symlink_target_id": symlink_target_id,
        },
    )


__all__ = [
    "emit_symlink_canonicalized",
    "emit_symlink_skipped",
]
