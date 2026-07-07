"""Row-anchored ``execution_lane`` resolution + cross-check for session-offer.

Encapsulates the contract: the authoritative ``execution_lane``
for a session offer is the value stored on the ``harness_sessions`` row
(written by ``session-begin`` from the executor default-lane lookup).
Caller-supplied ``--lane`` / request-body ``execution_lane`` values are
**advisory at most**. When they disagree with the row, the server:

1. Uses the row value for filtering, envelope authorship, and the
   downstream ``decide_next_action`` consumer.
2. Emits a WARN ``SessionOfferLaneOverrideIgnored`` event carrying
   both the caller-supplied value and the row's authoritative lane so
   the misbehaving caller surfaces in the events ledger.

The helper takes the row's ``execution_lane`` value as input (the
calling site already issued the ``SELECT`` for ``ended_at`` and is in
the best position to fetch the additional column in the same query).

Two-stage shape so the warning event fires **before** schedule
filtering, envelope merge, and ``decide_next_action`` see the lane:

- :func:`anchor_lane_on_row` returns the authoritative lane plus an
  optional cross-check payload describing the mismatch.
- :func:`emit_lane_override_ignored_event` consumes the payload and
  writes the WARN event.

Callers MUST emit the event before using the authoritative lane in
schedule filtering / envelope authorship / decision-engine input so
the event-ledger record cannot drift behind silent acceptance of the
caller value.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from runtime.harness.hook_helpers import is_codex

from . import sessions_analytics as _sa
from .sessions_lifecycle_canonicalize import canonicalize_executor

LANE_OVERRIDE_IGNORED_EVENT_NAME = "SessionOfferLaneOverrideIgnored"


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

    ``authoritative_lane`` is always the row value — that is the single
    source of truth callers must use for downstream work.

    ``mismatch_payload`` is non-``None`` when the caller supplied a
    non-empty ``execution_lane`` that differs from the row value AND
    is not the documented ``"default"`` sentinel that callers use to
    say "use the executor default". The payload is the ``context``
    dict for the warning event so the caller emits it verbatim.
    """

    authoritative_lane: str
    mismatch_payload: Optional[dict]


def _is_default_sentinel(value: Optional[str]) -> bool:
    """Return True when ``value`` is the documented ``"default"`` sentinel.

    ``resolve_execution_lane`` accepts ``"default"`` as a synonym for
    "use the executor default lane"; the row already carries that
    resolved value, so callers that pass ``--lane default`` are NOT
    asserting an override and must NOT trip the mismatch warning.
    The check is case-insensitive and tolerates leading/trailing
    whitespace.
    """
    if value is None:
        return False
    stripped = value.strip()
    if not stripped:
        return False
    return stripped.lower() == "default"


def anchor_lane_on_row(
    *,
    row_lane: Optional[str],
    caller_supplied_lane: Optional[str],
    resolved_lane: Optional[str] = None,
) -> LaneAnchorResult:
    """Resolve the authoritative lane and detect caller-vs-row mismatch.

    ``row_lane`` is the value read from ``harness_sessions.execution_lane``.
    ``caller_supplied_lane`` is the **raw** value the caller passed
    (CLI ``--lane`` argument or HTTP request-body ``execution_lane``);
    ``None`` (or empty) means "the caller did not pass a lane" and is
    NOT a mismatch. ``resolved_lane`` is the value that
    ``resolve_execution_lane`` would produce; the helper preserves it
    in the warning payload for telemetry but never uses it as a
    deciding factor.

    Returns the row value as authoritative regardless of the caller
    value, plus a mismatch payload (or ``None``) for the warning
    event. An empty row lane remains empty so the downstream lane
    policy gate can return ``lane_policy_unknown`` instead of silently
    routing through a caller/default fallback. ``None`` is returned
    for the payload when:

    - the caller did not supply a lane (``caller_supplied_lane`` is
      ``None`` or empty after whitespace strip),
    - the caller-supplied value is the documented ``"default"``
      sentinel (interpreted as "use the executor default"),
    - the caller value equals the row value (whitespace-normalised).

    The payload format is the ``context`` dict for
    ``SessionOfferLaneOverrideIgnored``, with three named values:

    - ``caller_supplied`` — the raw value the caller passed.
    - ``row_lane`` — the authoritative row value.
    - ``resolved_lane`` — the value that
      ``resolve_execution_lane`` produced (or the caller value when
      the resolver was never consulted).
    """
    if not row_lane or not row_lane.strip():
        return LaneAnchorResult(
            authoritative_lane="",
            mismatch_payload=None,
        )

    authoritative = row_lane.strip()

    if caller_supplied_lane is None:
        return LaneAnchorResult(authoritative_lane=authoritative, mismatch_payload=None)

    caller_stripped = caller_supplied_lane.strip()
    if not caller_stripped:
        return LaneAnchorResult(authoritative_lane=authoritative, mismatch_payload=None)

    if _is_default_sentinel(caller_stripped):
        return LaneAnchorResult(authoritative_lane=authoritative, mismatch_payload=None)

    if caller_stripped == authoritative:
        return LaneAnchorResult(authoritative_lane=authoritative, mismatch_payload=None)

    resolved_stripped = (resolved_lane or "").strip()
    payload = {
        "caller_supplied": caller_stripped,
        "row_lane": authoritative,
        "resolved_lane": resolved_stripped or caller_stripped,
    }
    return LaneAnchorResult(authoritative_lane=authoritative, mismatch_payload=payload)


def emit_lane_override_ignored_event(
    *,
    session_id: str,
    project: Optional[str],
    payload: dict,
) -> None:
    """Emit the canonical WARN ``SessionOfferLaneOverrideIgnored`` event.

    ``payload`` is the dict returned by :func:`anchor_lane_on_row` as
    ``mismatch_payload``. Callers that received ``None`` for the
    payload do NOT call this function.

    The event carries ``severity="WARN"`` and routes through the same
    ``sessions_analytics._emit_event`` helper that ``HarnessSessionOffered``
    uses, so the row lands in the standard ``events`` ledger and is
    discoverable via ``db_router events list --event-name SessionOfferLaneOverrideIgnored``.
    """
    _sa._emit_event(
        LANE_OVERRIDE_IGNORED_EVENT_NAME,
        event_kind="system",
        event_type="session_offer_lane_override_ignored",
        source_type="backend",
        session_id=session_id,
        project=project,
        context=dict(payload),
        outcome="completed",
        severity="WARN",
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

    ``execution_lane`` is the **authoritative** lane (row-anchored
    after :func:`anchor_lane_on_row`); the helper does not consult
    any caller-supplied value.

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
        envelope["executor_display_name"] = display_name
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
    """Emit the canonical ``HarnessSessionOffered`` event with row-anchored lane."""
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
        context["executor_display_name"] = display_name
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
    "LANE_OVERRIDE_IGNORED_EVENT_NAME",
    "LaneAnchorResult",
    "anchor_lane_on_row",
    "build_offer_envelope",
    "emit_lane_override_ignored_event",
    "emit_session_offered_event",
    "merge_offer_envelope",
]
