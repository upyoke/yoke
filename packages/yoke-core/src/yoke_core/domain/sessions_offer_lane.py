"""Session-offer ``execution_lane`` resolution.

The ``harness_sessions.execution_lane`` value (written by
``session-begin`` from the executor default-lane lookup) is the
**default**. A caller-supplied ``--lane`` / request-body
``execution_lane`` overrides that default. When they disagree, the
server:

1. Uses the caller value for filtering, envelope authorship, and the
   downstream ``decide_next_action`` consumer.
2. Emits ``SessionOfferLaneOverrideApplied`` carrying
   ``caller_supplied``, ``row_lane``, and ``resolved_lane``.

Two-stage shape so the event fires **before** schedule filtering,
envelope merge, and ``decide_next_action`` see the lane:

- :func:`anchor_lane_on_row` returns the resolved lane plus an
  optional override payload.
- :func:`emit_lane_override_applied_event` consumes the payload and
  writes the event.

Callers MUST emit the event before using the resolved lane downstream
so the ledger cannot drift behind silent acceptance of the caller
value.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from yoke_harness.hooks.identity import is_codex

from . import sessions_analytics as _sa
from .sessions_lifecycle_canonicalize import canonicalize_executor

LANE_OVERRIDE_APPLIED_EVENT_NAME = "SessionOfferLaneOverrideApplied"


def merge_offer_envelope(
    existing_blob: Optional[str],
    per_offer: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge per-offer identity/step fields over the existing envelope.

    Preserves cross-offer state written by other code paths between
    offers (``chain_skip_memory``, ``chain_checkpoint``,
    ``runtime_session_id``, etc.) while letting per-offer identity
    keys overwrite their prior values.

    A missing, empty, malformed, or non-dict existing blob is treated
    as no prior state — the merge returns the per-offer dict
    unchanged.
    """
    if existing_blob:
        try:
            parsed = json.loads(existing_blob)
        except (json.JSONDecodeError, TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            merged = dict(parsed)
            merged.update(per_offer)
            return merged
    return dict(per_offer)


@dataclass(frozen=True)
class LaneAnchorResult:
    """Outcome of :func:`anchor_lane_on_row`.

    ``authoritative_lane`` is the lane callers must use downstream:
    the caller-supplied value when one was passed (and is not the
    ``default`` sentinel), otherwise the row value.

    ``override_payload`` is non-``None`` when the caller supplied a
    non-empty ``execution_lane`` that differs from the row value AND
    is not the documented ``default`` sentinel. The payload is the
    ``context`` dict for the override event so the caller emits it
    verbatim.
    """

    authoritative_lane: str
    override_payload: Optional[dict]


def _is_default_sentinel(value: Optional[str]) -> bool:
    """Return True when ``value`` is the documented ``default`` sentinel.

    ``resolve_execution_lane`` accepts ``default`` as a synonym for
    "use the executor default lane"; the row already carries that
    resolved value, so callers that pass ``--lane default`` are NOT
    asserting an override. The check is case-insensitive and
    tolerates leading/trailing whitespace.
    """
    if value is None:
        return False
    stripped = value.strip()
    if not stripped:
        return False
    return stripped.lower() == "default"


def _strip_or_empty(value: Optional[str]) -> str:
    if value is None:
        return ""
    return value.strip()


def anchor_lane_on_row(
    *,
    row_lane: Optional[str],
    caller_supplied_lane: Optional[str],
    resolved_lane: Optional[str] = None,
) -> LaneAnchorResult:
    """Resolve the offer lane and detect an applied caller override.

    ``row_lane`` is the value read from ``harness_sessions.execution_lane``.
    ``caller_supplied_lane`` is the **raw** value the caller passed
    (CLI ``--lane`` or HTTP request-body ``execution_lane``);
    ``None`` (or empty) means "the caller did not pass a lane".
    ``resolved_lane`` is the value that ``resolve_execution_lane``
    would produce; the helper preserves it in the event payload for
    telemetry but never uses it as a deciding factor.

    A supplied caller lane (other than the ``default`` sentinel) wins.
    An empty row lane remains empty when the caller did not supply a
    lane so the downstream lane policy gate can return
    ``lane_policy_unknown``. ``None`` is returned for the payload
    when:

    - the caller did not supply a lane,
    - the caller-supplied value is the ``default`` sentinel,
    - the caller value equals the row value (whitespace-normalised).

    The payload format is the ``context`` dict for
    ``SessionOfferLaneOverrideApplied``, with three named values:

    - ``caller_supplied`` — the raw value the caller passed.
    - ``row_lane`` — the row default.
    - ``resolved_lane`` — the value that
      ``resolve_execution_lane`` produced (or the caller value when
      the resolver was never consulted).
    """
    row = _strip_or_empty(row_lane)
    caller = _strip_or_empty(caller_supplied_lane)

    if not caller or _is_default_sentinel(caller):
        return LaneAnchorResult(authoritative_lane=row, override_payload=None)

    if caller == row:
        return LaneAnchorResult(authoritative_lane=caller, override_payload=None)

    resolved_stripped = _strip_or_empty(resolved_lane)
    payload = {
        "caller_supplied": caller,
        "row_lane": row,
        "resolved_lane": resolved_stripped or caller,
    }
    return LaneAnchorResult(authoritative_lane=caller, override_payload=payload)


def emit_lane_override_applied_event(
    *,
    session_id: str,
    project: Optional[str],
    payload: dict,
    conn: Any = None,
) -> None:
    """Emit ``SessionOfferLaneOverrideApplied``.

    ``payload`` is the dict returned by :func:`anchor_lane_on_row` as
    ``override_payload``. Callers that received ``None`` for the
    payload do NOT call this function.

    Pass the offer connection so the row commits with the offer
    transaction. A conn-less emit is isolation-gated in tests and can
    miss the fixture database.
    """
    from .events import emit_event
    from .events_schema import ensure_event_schema

    if conn is not None:
        ensure_event_schema(conn)
    emit_event(
        LANE_OVERRIDE_APPLIED_EVENT_NAME,
        event_kind="system",
        event_type="session_offer_lane_override_applied",
        source_type="backend",
        session_id=session_id,
        project=project or "yoke",
        context=dict(payload),
        outcome="completed",
        severity="INFO",
        conn=conn,
    )


def build_offer_envelope(
    *,
    session_id: str,
    executor: str,
    provider: str,
    model: str,
    workspace: str,
    execution_lane: str,
    capabilities: Optional[List[str]],
    step: int,
    supported_paths: List[str],
    max_chain_steps: int,
    project_scope: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Build the per-offer identity dict written into ``harness_sessions.offer_envelope``.

    ``execution_lane`` is the resolved lane after
    :func:`anchor_lane_on_row`.

    Persists the Codex thread UUID under ``runtime_session_id`` when
    the executor is a Codex variant so cross-process telemetry can
    correlate the registered session with the underlying Codex thread.

    ``project_scope`` persists the resolved set of project ids the offer
    was scoped to. On reactivation, an envelope lacking ``project_scope``
    is treated as the all-projects default.
    """
    canonical_executor, display_name = canonicalize_executor(executor, None)
    envelope: Dict[str, Any] = {
        "session_id": session_id,
        "executor": canonical_executor,
        "provider": provider,
        "model": model,
        "workspace": workspace,
        "execution_lane": execution_lane,
        "capabilities": list(capabilities or []),
        "step": step,
        "supported_paths": list(supported_paths),
        "max_chain_steps": max_chain_steps,
        "project_scope": list(project_scope or []),
    }
    if display_name:
        envelope["executor_surface"] = display_name
    if is_codex(canonical_executor):
        codex_thread = os.environ.get("CODEX_THREAD_ID", "")
        if codex_thread:
            envelope["runtime_session_id"] = codex_thread
    return envelope


def emit_session_offered_event(
    *,
    session_id: str,
    project: Optional[str],
    project_scope: Optional[List[int]] = None,
    executor: str,
    provider: str,
    model: str,
    workspace: str,
    execution_lane: str,
    capabilities: Optional[List[str]],
    step: int,
    supported_paths: List[str],
) -> None:
    """Emit the canonical ``HarnessSessionOffered`` event with the resolved lane."""
    canonical_executor, display_name = canonicalize_executor(executor, None)
    context: Dict[str, Any] = {
        "session_id": session_id,
        "executor": canonical_executor,
        "provider": provider,
        "model": model,
        "execution_lane": execution_lane,
        "workspace": workspace,
        "capabilities": list(capabilities or []),
        "step": step,
        "supported_paths": list(supported_paths),
        "project_scope": list(project_scope or []),
    }
    if display_name:
        context["executor_surface"] = display_name
    _sa._emit_event(
        "HarnessSessionOffered",
        event_kind="system",
        event_type="session_offer",
        source_type="backend",
        session_id=session_id,
        project=project,
        context=context,
    )


__all__ = [
    "LANE_OVERRIDE_APPLIED_EVENT_NAME",
    "LaneAnchorResult",
    "anchor_lane_on_row",
    "build_offer_envelope",
    "emit_lane_override_applied_event",
    "emit_session_offered_event",
    "merge_offer_envelope",
]
