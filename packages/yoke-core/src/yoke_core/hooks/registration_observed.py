"""Wire-carried and locally observed session registration facts."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Optional

from yoke_contracts.session_model_facts import SessionModelFacts, facts_from_mapping
from yoke_core.domain.session_model_normalization import reclassify_unservable_model


@dataclass(frozen=True)
class HookRegistrationFacts:
    #: The model facts the relaying client already resolved, when the
    #: payload came over the wire. Empty for a local payload, which the
    #: caller then resolves against this machine's own evidence.
    model_facts: SessionModelFacts = field(default_factory=SessionModelFacts)
    entrypoint: str = ""
    execution_level: str = ""
    executor_version: str = ""
    machine_id: str = ""
    native_thread_id: str = ""
    #: The launch that started this session, read from the authenticated
    #: ``yoke_launch`` side channel the launch handoff projects into the
    #: payload. Present only while that launch is still undelivered; a
    #: session nobody launched carries none.
    launch_id: str = ""
    #: An absent project registers under this authority's organization.
    project_id: Optional[int] = None
    transcript_path: str = ""
    #: The harness workspace the session opened, from the first path the
    #: payload names: Cursor's ``workspace_roots`` lead, then ``cwd`` (Claude,
    #: Codex, and Cursor tool events). A launch binds its native by this path.
    workspace: str = ""
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
    from yoke_contracts.hook_runner.project_scope import workspace_path_candidates

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
        execution_level=_text("execution_level"),
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
        workspace=next(iter(workspace_path_candidates(payload)), "").strip(),
        driver=_driver_block(payload),
    )


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
        from yoke_contracts.runtime_ports.identity_observed import get_identity_observed
        client_executor_version = get_identity_observed().client_executor_version
        client_machine_id = get_identity_observed().client_machine_id

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
