"""Server-side evaluation entry of the https hook-relay split.

``evaluate_remote`` (server side, ``POST /v1/hooks/evaluate``) reuses
:func:`yoke_core.hooks.runner.run_event` with a capability
built from the REQUEST's executor (never server detection) and the
request's ``agent_type`` merged into the payload, where payload-keyed
detection (e.g. ``lint_subagent_background``) already reads it. Classified
local-state policies self-skip into ``degraded``
(:mod:`yoke_core.hooks.remote_policy`) — the relay client owns
them via its product-owned subset (``yoke_harness.hooks.local_subset``).
The verified bearer-token ``actor_id`` rides the controls so the
ensure-register tail binds it to the ``harness_sessions`` row.

The request's ``deadline_ms`` is clamped to the server ceiling; a deny
computed before expiry is preserved in the rendered output.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from yoke_contracts.session_model_facts import MODEL_FACT_FIELDS, SessionModelFacts

from yoke_core.hooks.capability_resolve import resolve_capability
from yoke_core.domain.hook_runner_deadline import resolve_total_timeout_ms
from yoke_core.hooks.remote_policy import (
    DEADLINE_EXHAUSTED_MARKER,
    RunControls,
    remote_skip_marker,
)
from yoke_core.hooks.runner import run_event


__all__ = [
    "RemoteEvaluation",
    "evaluate_remote",
]


@dataclass(frozen=True)
class RemoteEvaluation:
    """Outcome of one remote hook evaluation."""

    stdout: str
    exit_code: int
    degraded: tuple[str, ...]
    wait_ms: int
    outcome: str  # completed | timeout | denied
    denial_audit: dict[str, str]


def evaluate_remote(
    event_name: str,
    stdin_data: str,
    executor: str,
    agent_type: Optional[str],
    deadline_ms: int,
    entrypoint: Optional[str] = None,
    model_facts: Optional[SessionModelFacts] = None,
    execution_lane: Optional[str] = None,
    project_id: Optional[int] = None,
    executor_version: Optional[str] = None,
    machine_id: Optional[str] = None,
    native_thread_id: Optional[str] = None,
    payload_extra: Optional[dict] = None,
    actor_id: Optional[int] = None,
) -> RemoteEvaluation:
    """Evaluate one hook event server-side; never raises past run_event."""
    budget_ms = max(1, min(int(deadline_ms), resolve_total_timeout_ms()))
    controls = RunControls(
        budget_ms=budget_ms,
        skip_module=remote_skip_marker,
        remote=True,
        actor_id=actor_id,
    )
    if isinstance(payload_extra, dict):
        controls.payload_extra.update(payload_extra)
    if agent_type and agent_type.strip():
        controls.payload_extra["agent_type"] = agent_type.strip()
    # Client-side identity facts the server cannot detect itself: the
    # caller's entrypoint (desktop vs CLI display), the model facts read
    # from the harness's own artifact and launch environment, and the
    # config-resolved execution lane ride the wire and merge into the
    # payload, where the registration path already prefers them.
    if entrypoint and entrypoint.strip():
        controls.payload_extra["entrypoint"] = entrypoint.strip()
    for field in MODEL_FACT_FIELDS:
        value = getattr(model_facts, field, None) if model_facts else None
        if value is not None:
            controls.payload_extra[field] = value
    if execution_lane and execution_lane.strip():
        controls.payload_extra["execution_lane"] = execution_lane.strip()
    if project_id is not None:
        controls.payload_extra["project_id"] = int(project_id)
    if executor_version and executor_version.strip():
        controls.payload_extra["executor_version"] = executor_version.strip()
    if machine_id and machine_id.strip():
        controls.payload_extra["machine_id"] = machine_id.strip()
    if native_thread_id and native_thread_id.strip():
        controls.payload_extra["native_thread_id"] = native_thread_id.strip()
    capability = resolve_capability(executor)

    started = time.monotonic()
    stdout, exit_code = run_event(
        event_name,
        capability=capability,
        stdin_data=stdin_data,
        controls=controls,
    )
    wait_ms = int((time.monotonic() - started) * 1000)

    degraded = list(controls.degraded)
    if controls.timed_out:
        degraded.append(DEADLINE_EXHAUSTED_MARKER)
    if controls.final_outcome == "deny":
        outcome = "denied"
    elif controls.timed_out:
        outcome = "timeout"
    else:
        outcome = "completed"
    return RemoteEvaluation(
        stdout=stdout,
        exit_code=exit_code,
        degraded=tuple(degraded),
        wait_ms=wait_ms,
        outcome=outcome,
        denial_audit=dict(controls.denial_audit),
    )
