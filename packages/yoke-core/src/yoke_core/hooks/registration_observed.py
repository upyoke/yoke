"""Wire-carried and locally observed session registration facts."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Optional

from yoke_contracts.session_model_facts import SessionModelFacts, facts_from_mapping


@dataclass(frozen=True)
class HookRegistrationFacts:
    #: The model facts the relaying client already resolved, when the
    #: payload came over the wire. Empty for a local payload, which the
    #: caller then resolves against this machine's own evidence.
    model_facts: SessionModelFacts = field(default_factory=SessionModelFacts)
    entrypoint: str = ""
    execution_lane: str = ""
    executor_version: str = ""
    machine_id: str = ""
    native_thread_id: str = ""
    #: The launch that started this session, read from the authenticated
    #: ``yoke_launch`` side channel the launch handoff projects into the
    #: payload. Present only while that launch is still undelivered; a
    #: session nobody launched carries none.
    launch_id: str = ""
    project_id: Optional[int] = None
    transcript_path: str = ""
    cwd: str = ""
    #: The process and hook event that drove this registration, resolved by
    #: the dispatch tail. Empty for registration paths that carry no hook
    #: dispatch behind them (an operator surface calling the registrar).
    driver: Optional[dict] = None


def _positive_int(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def parse_hook_registration_facts(
    payload_json: str,
    *,
    project_id: Optional[int],
    transcript_path: str,
) -> HookRegistrationFacts:
    """Parse only the bounded scalar identity fields carried by a hook."""
    try:
        payload = json.loads(payload_json) if payload_json else {}
    except (json.JSONDecodeError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    def _text(key: str) -> str:
        value = payload.get(key, "")
        return value.strip() if isinstance(value, str) else ""

    return HookRegistrationFacts(
        model_facts=reclassify_unservable_model(facts_from_mapping(payload)),
        entrypoint=_text("entrypoint"),
        execution_lane=_text("execution_lane"),
        executor_version=_text("executor_version"),
        machine_id=_text("machine_id"),
        native_thread_id=_text("native_thread_id"),
        launch_id=_launch_id(payload),
        project_id=(
            project_id
            if project_id is not None
            else _positive_int(payload.get("project_id"))
        ),
        transcript_path=transcript_path or _text("transcript_path"),
        cwd=_text("cwd"),
        driver=_driver_block(payload),
    )


def reclassify_unservable_model(facts: SessionModelFacts) -> SessionModelFacts:
    """Move a wire ``model`` no provider could have served off that slot.

    A placeholder such as ``unknown`` is the absence of an answer and is
    dropped. A context tier selector such as ``claude-opus-5[1m]`` is an
    ask — no provider response returns one — and a client older than this
    contract ships its requested model under the plain key, so during the
    rollout window that is exactly what arrives. It moves to the request
    slot rather than being discarded, because that is what it always was.
    """
    from dataclasses import replace

    from yoke_contracts.session_model_facts import CLAUDE_CONTEXT_TIER_SUFFIX
    from yoke_harness.hooks.identity import _is_placeholder_model

    model = facts.model
    if model is None:
        return facts
    if _is_placeholder_model(model):
        return replace(facts, model=None)
    if not model.strip().lower().endswith(CLAUDE_CONTEXT_TIER_SUFFIX):
        return facts
    if facts.requested_model:
        return replace(facts, model=None)
    return replace(facts, model=None, requested_model=model)


def _launch_id(payload: dict) -> str:
    """Return the launch id the attestation side channel carried, if any."""
    block = payload.get("yoke_launch")
    if not isinstance(block, dict):
        return ""
    launch_id = block.get("launch_id")
    return launch_id.strip() if isinstance(launch_id, str) else ""


def _driver_block(payload: dict) -> Optional[dict]:
    """Return the dispatch tail's driving-process block, when it rode along."""
    from yoke_contracts.hook_driver_process import DRIVER_PAYLOAD_KEY

    block = payload.get(DRIVER_PAYLOAD_KEY)
    return dict(block) if isinstance(block, dict) and block else None


def enrich_local_observed_facts(
    executor_version: str,
    machine_id: str,
    executor: str = "",
    *,
    executor_surface: str | None = None,
) -> tuple[str, str]:
    """Fill absent wire facts using client-safe probes, best effort.

    ``executor`` names the harness family so a surface the harness reported
    in its own family-relative vocabulary resolves to the shared probe key.
    """
    if executor_version and machine_id:
        return executor_version, machine_id
    try:
        from yoke_harness.hooks.identity_observed import (
            client_executor_version,
            client_machine_id,
        )

        return (
            executor_version
            or client_executor_version(executor, executor_surface)
            or "",
            machine_id or client_machine_id() or "",
        )
    except Exception:  # noqa: BLE001 - registration enrichment is best effort
        return executor_version, machine_id


__all__ = [
    "HookRegistrationFacts",
    "enrich_local_observed_facts",
    "parse_hook_registration_facts",
]
