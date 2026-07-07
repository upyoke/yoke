"""Materialization-state event emitters for path_targets.

Companion module to :mod:`yoke_core.domain.path_claims_events`. The
two share the same emission shape (decision-shaped payload, INFO
severity, `lifecycle` event-kind) so consumers do not need to special-
case the path-target lifecycle separately from the claim lifecycle.

Four event names cover the materialization state machine:

* ``PathTargetPlanned`` — a path_targets row was minted (or re-planned
  from ``abandoned`` / upgraded from ``tentative``) with
  ``materialization_state='planned'`` for an exact future path.
* ``PathTargetTentative`` — a path_targets row was minted (or re-planned
  from ``abandoned``) with ``materialization_state='tentative'`` for an
  exact predicted-but-uncertain path.
* ``PathTargetMaterialized`` — git later observed the planned/tentative
  path and the snapshot scanner flipped the existing row to
  ``materialization_state='observed'``, preserving claim identity.
* ``PathTargetAbandoned`` — the planned/tentative target is no longer
  expected to appear (claim cancelled, item amended away). State flips
  to ``abandoned``.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


_EVENT_KIND = "lifecycle"
_EVENT_TYPE = "path_target"
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
    """Best-effort emit; return event id or ``None`` on failure."""
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
    except Exception:  # noqa: BLE001 — emit is best-effort
        return None
    if not envelope.ok:
        return None
    return envelope.event_id


def _common_target_context(
    *,
    target_id: int,
    project_id: str,
    path_string: str,
    kind: str,
    generation: int,
    parent_target_id: Optional[int],
    old_state: Optional[str],
    new_state: str,
) -> Dict[str, Any]:
    return {
        "target_id": target_id,
        "project_id": project_id,
        "path_string": path_string,
        "kind": kind,
        "generation": generation,
        "parent_target_id": parent_target_id,
        "old_state": old_state,
        "new_state": new_state,
    }


_PRE_OBSERVATION_EVENT_NAMES = {
    "planned": "PathTargetPlanned",
    "tentative": "PathTargetTentative",
}


def emit_pre_observation(
    *,
    conn: Any,
    target_id: int,
    project_id: str,
    path_string: str,
    kind: str,
    generation: int,
    parent_target_id: Optional[int],
    item_id: Optional[int],
    claim_id: Optional[int],
    old_state: Optional[str],
    new_state: str,
    session_id: Optional[str] = None,
) -> Optional[str]:
    """Emit the planned/tentative event matching ``new_state``.

    Single dispatcher for the two pre-observation states so callers in
    :mod:`yoke_core.domain.path_targets_planning` do not branch on
    the state literal at every emit site.
    """
    event_name = _PRE_OBSERVATION_EVENT_NAMES.get(new_state)
    if event_name is None:
        raise ValueError(
            f"emit_pre_observation: unsupported new_state {new_state!r}; "
            f"expected one of {sorted(_PRE_OBSERVATION_EVENT_NAMES)}"
        )
    context = _common_target_context(
        target_id=target_id,
        project_id=project_id,
        path_string=path_string,
        kind=kind,
        generation=generation,
        parent_target_id=parent_target_id,
        old_state=old_state,
        new_state=new_state,
    )
    context["item_id"] = item_id
    context["claim_id"] = claim_id
    return _emit(
        name=event_name,
        severity="INFO",
        outcome="completed",
        conn=conn,
        item_id=item_id,
        project=project_id,
        session_id=session_id,
        context=context,
    )


def emit_planned(
    *,
    conn: Any,
    target_id: int,
    project_id: str,
    path_string: str,
    kind: str,
    generation: int,
    parent_target_id: Optional[int],
    item_id: Optional[int],
    claim_id: Optional[int],
    old_state: Optional[str],
    session_id: Optional[str] = None,
) -> Optional[str]:
    """Emit ``PathTargetPlanned`` for a freshly minted or re-planned target."""
    return emit_pre_observation(
        conn=conn,
        target_id=target_id,
        project_id=project_id,
        path_string=path_string,
        kind=kind,
        generation=generation,
        parent_target_id=parent_target_id,
        item_id=item_id,
        claim_id=claim_id,
        old_state=old_state,
        new_state="planned",
        session_id=session_id,
    )


def emit_materialized(
    *,
    conn: Any,
    target_id: int,
    project_id: str,
    path_string: str,
    kind: str,
    generation: int,
    parent_target_id: Optional[int],
    commit_sha: str,
    item_id: Optional[int] = None,
    claim_id: Optional[int] = None,
    session_id: Optional[str] = None,
) -> Optional[str]:
    """Emit ``PathTargetMaterialized`` when a planned target turns observed."""
    context = _common_target_context(
        target_id=target_id,
        project_id=project_id,
        path_string=path_string,
        kind=kind,
        generation=generation,
        parent_target_id=parent_target_id,
        old_state="planned",
        new_state="observed",
    )
    context["commit_sha"] = commit_sha
    context["item_id"] = item_id
    context["claim_id"] = claim_id
    return _emit(
        name="PathTargetMaterialized",
        severity="INFO",
        outcome="completed",
        conn=conn,
        item_id=item_id,
        project=project_id,
        session_id=session_id,
        context=context,
    )


def emit_abandoned(
    *,
    conn: Any,
    target_id: int,
    project_id: str,
    path_string: str,
    kind: str,
    generation: int,
    parent_target_id: Optional[int],
    reason: str,
    item_id: Optional[int] = None,
    claim_id: Optional[int] = None,
    session_id: Optional[str] = None,
) -> Optional[str]:
    """Emit ``PathTargetAbandoned`` when a planned target is no longer expected."""
    context = _common_target_context(
        target_id=target_id,
        project_id=project_id,
        path_string=path_string,
        kind=kind,
        generation=generation,
        parent_target_id=parent_target_id,
        old_state="planned",
        new_state="abandoned",
    )
    context["reason"] = reason
    context["item_id"] = item_id
    context["claim_id"] = claim_id
    return _emit(
        name="PathTargetAbandoned",
        severity="INFO",
        outcome="completed",
        conn=conn,
        item_id=item_id,
        project=project_id,
        session_id=session_id,
        context=context,
    )


__all__ = [
    "emit_abandoned",
    "emit_materialized",
    "emit_planned",
    "emit_pre_observation",
]
