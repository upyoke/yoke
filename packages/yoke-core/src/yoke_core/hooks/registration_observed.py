"""Wire-carried and locally observed session registration facts."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class HookRegistrationFacts:
    model: str = ""
    entrypoint: str = ""
    execution_lane: str = ""
    executor_version: str = ""
    machine_id: str = ""
    native_thread_id: str = ""
    project_id: Optional[int] = None
    transcript_path: str = ""
    cwd: str = ""


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
    is_placeholder_model: Callable[[str], bool],
) -> HookRegistrationFacts:
    """Parse only the bounded scalar identity fields carried by a hook."""
    try:
        payload = json.loads(payload_json) if payload_json else {}
    except (json.JSONDecodeError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    model = payload.get("model", "")
    model = model if isinstance(model, str) else ""
    if not model or is_placeholder_model(model):
        model = ""

    def _text(key: str) -> str:
        value = payload.get(key, "")
        return value.strip() if isinstance(value, str) else ""

    return HookRegistrationFacts(
        model=model,
        entrypoint=_text("entrypoint"),
        execution_lane=_text("execution_lane"),
        executor_version=_text("executor_version"),
        machine_id=_text("machine_id"),
        native_thread_id=_text("native_thread_id"),
        project_id=(
            project_id
            if project_id is not None
            else _positive_int(payload.get("project_id"))
        ),
        transcript_path=transcript_path or _text("transcript_path"),
        cwd=_text("cwd"),
    )


def enrich_local_observed_facts(
    executor: str,
    executor_version: str,
    machine_id: str,
    *,
    executor_surface: str | None = None,
) -> tuple[str, str]:
    """Fill absent wire facts using client-safe probes, best effort."""
    if executor_version and machine_id:
        return executor_version, machine_id
    try:
        from yoke_harness.hooks.identity_observed import (
            client_executor_version,
            client_machine_id,
        )

        return (
            executor_version
            or client_executor_version(
                executor,
                executor_surface=executor_surface,
            )
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
