"""Model facts on the relayed wire, and the settling that ends resolving.

Resolving served model facts reads a transcript or conversation store, so
a session stops resolving once its model has reached the control plane.
That settle point is bound to a LANDED write, never to a local read: a
hook whose relay fails open, times out, or degrades carries the model
nowhere, and a session that settled on the read alone would never mention
its model again — leaving ``harness_sessions.model`` NULL for its whole
life. Callers resolve with :func:`client_model_facts`, send, and only then
call :func:`record_model_facts_shipped` with what the control plane
accepted.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import machine_config
from yoke_contracts.executor_labels import canonical_harness_id
from yoke_contracts.session_context_window_sources import records_window_separately
from yoke_contracts.session_model_facts import (
    MODEL_FACT_FIELDS,
    SessionModelFacts,
)


REGISTRATION_EVENTS = frozenset({"SessionStart", "UserPromptSubmit"})

_MODEL_SHIPPED_DIR_NAME = "relay-model-shipped"
_MODEL_SHIPPED_PRUNE_AGE_S = 7 * 86400


def _model_shipped_marker(session_id: str) -> Path:
    return machine_config.yoke_home() / _MODEL_SHIPPED_DIR_NAME / session_id


def _mark_model_shipped(session_id: str) -> None:
    try:
        marker = _model_shipped_marker(session_id)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        cutoff = time.time() - _MODEL_SHIPPED_PRUNE_AGE_S
        for entry in marker.parent.iterdir():
            try:
                if entry.stat().st_mtime < cutoff:
                    entry.unlink()
            except OSError:
                continue
    except Exception:
        return


def model_facts_settled(event_name: str, session_id: str) -> bool:
    """True when this session's model facts need not be resolved again.

    Resolution reads a transcript or conversation store, so a served model
    marker stops later work. The marker exists only where a hook carrying
    the model completed against the control plane. Registration events
    always resolve; unmarked sessions keep trying until the harness
    artifact exists AND an evaluation carrying it lands.
    """
    if event_name in REGISTRATION_EVENTS:
        return False
    if not session_id:
        return True
    try:
        return _model_shipped_marker(session_id).exists()
    except Exception:
        return True


def record_model_facts_shipped(
    payload: Mapping[str, Any],
    identity: Mapping[str, Any],
) -> None:
    """Settle this session once an evaluation carrying its model landed.

    Call this only where the control plane accepted the write — a relayed
    evaluation that returned the hook contract without timing out, or an
    in-process run that completed. A transport failure, a timeout, or a
    degraded fail-open must NOT reach here: the whole point of the marker
    is that the served model is recorded somewhere other than this
    machine, and settling on an unsent read is how a session's model stays
    NULL for the rest of its life.
    """
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return
    if identity.get("model") is None:
        return
    _mark_model_shipped(session_id)


def resolve_model_facts(payload: dict[str, Any], executor: str) -> SessionModelFacts:
    """Resolve both halves of this session's model facts from the machine.

    The ask comes from the launch environment; the served truth comes from
    the harness's own artifact. Either half may be empty — an artifact that
    has not been written yet attests nothing — and neither ever stands in
    for the other.
    """
    try:
        from yoke_harness.model_attestation import attest_served_facts
        from yoke_harness.model_request import requested_facts

        transcript = payload.get("transcript_path")
        served = attest_served_facts(
            executor,
            payload,
            transcript_path=transcript if isinstance(transcript, str) else "",
        )
        asked = requested_facts(executor, payload)
    except Exception:  # noqa: BLE001 — identity probes never break a hook
        return SessionModelFacts()
    return SessionModelFacts(
        model=served.model,
        reasoning_effort=served.reasoning_effort,
        context_window_tokens=served.context_window_tokens,
        requested_model=asked.requested_model,
        requested_reasoning_effort=asked.requested_reasoning_effort,
        requested_context_window_tokens=asked.requested_context_window_tokens,
    )


def client_model_facts(
    event_name: str, payload: dict[str, Any], executor: str
) -> dict[str, Any]:
    """Model facts for the relayed wire, or ``{}`` once they are settled.

    Absent keys mean "nothing to say"; an explicit value is either what was
    asked or what a provider reported, never one standing in for the other.
    Resolving here never settles the session — only a landed write does,
    through :func:`record_model_facts_shipped`.
    """
    session_id = payload.get("session_id")
    session_id = session_id if isinstance(session_id, str) else ""
    if model_facts_settled(event_name, session_id):
        return _recorded_window_facts(session_id, executor)
    facts = resolve_model_facts(payload, executor)
    return {
        field: getattr(facts, field)
        for field in MODEL_FACT_FIELDS
        if getattr(facts, field) is not None
    }


def _recorded_window_facts(session_id: str, executor: str) -> dict[str, Any]:
    """The one served fact that can still arrive after a session settles.

    Settling ends the expensive reads, and it has to: a proven model is the
    whole answer a transcript or store will give. Claude's window is the
    exception — a different process writes it on its own schedule, after the
    model is known — so it is looked for past the settle point, affordable
    only because that lookup opens one small file rather than re-reading an
    artifact. A stored window resends harmlessly; the merge drops it.
    """
    try:
        if not records_window_separately(canonical_harness_id(executor)):
            return {}
        from yoke_harness.claude_status_line import recorded_context_window

        window = recorded_context_window(session_id)
    except Exception:  # noqa: BLE001 — identity probes never break a hook
        return {}
    return {"context_window_tokens": window} if window is not None else {}


__all__ = [
    "REGISTRATION_EVENTS",
    "client_model_facts",
    "model_facts_settled",
    "record_model_facts_shipped",
    "resolve_model_facts",
]
