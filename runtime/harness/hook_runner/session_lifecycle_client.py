"""Harness-neutral session lifecycle client helpers."""

from __future__ import annotations

import shlex
from typing import Optional

from runtime.harness.hook_runner import service_client, target


def _project_id_for_root(root: str) -> Optional[int]:
    try:
        from yoke_core.domain import machine_config

        return machine_config.project_id(root)
    except Exception:
        return None


def service_client_path(root: str) -> str:
    """Return the service client that can mutate lifecycle state for ``root``."""
    return target.target_service_client_path(root)


def register_harness_session(
    *,
    root: str,
    session_id: str,
    executor: str,
    provider: str,
    model: str,
    entrypoint: Optional[str] = None,
) -> str:
    """Register a harness session through the target-aware service client.

    On https-default machines this self-skips and reports success: the
    local service-client subprocess has no local authority to reach, and
    the relayed hook chain's server-side ensure-register owns the
    session row (every relayed event drives it). Attempting the doomed
    subprocess made every Claude/Codex orientation block print a false
    "Session registration failed - scheduler will not see this session"
    warning while the row was healthy server-side.
    """
    if _relay_owns_registration():
        return ""
    project_id = _project_id_for_root(root)
    if project_id is None:
        return "session registration requires a configured project_id for this checkout"
    return service_client.register_session(
        service_client_path(root),
        session_id,
        executor,
        provider,
        model,
        root,
        entrypoint,
        project_id,
    ) or ""


def _relay_owns_registration() -> bool:
    """True when the machine's active transport is https.

    Any config read failure resolves False so local-transport behavior
    is untouched.
    """
    try:
        from yoke_core.domain.machine_config import active_connection
        from yoke_contracts.machine_config.schema import TRANSPORT_HTTPS

        return str(active_connection().get("transport") or "") == TRANSPORT_HTTPS
    except Exception:  # noqa: BLE001 — registration must not break on config
        return False


def touch_harness_session(root: str, session_id: str) -> int:
    """Heartbeat a harness session through the target-aware service client."""
    return service_client.touch_session(service_client_path(root), root, session_id)


def session_begin_recovery_command(
    *,
    root: str,
    session_id: str,
    executor: str,
    provider: str,
    model: str,
    entrypoint: Optional[str] = None,
) -> str:
    """Render an operator recovery command for the target-aware service client."""
    parts = [
        "python3",
        service_client_path(root),
        "session-begin",
        "--session-id",
        session_id,
        "--executor",
        executor,
        "--provider",
        provider,
        "--model",
        model,
        "--workspace",
        root,
    ]
    project_id = _project_id_for_root(root)
    if project_id is not None:
        parts.extend(["--project-id", str(project_id)])
    if entrypoint:
        parts.extend(["--entrypoint", entrypoint])
    return " ".join(shlex.quote(part) for part in parts)
