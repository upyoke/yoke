"""Harness-neutral session lifecycle client helpers."""

from __future__ import annotations

import shlex
from typing import Optional

from yoke_contracts.session_model_facts import SessionModelFacts

from yoke_core.hooks import service_client, target


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
    model_facts: SessionModelFacts,
    entrypoint: Optional[str] = None,
    executor_version: Optional[str] = None,
    machine_id: Optional[str] = None,
    native_thread_id: Optional[str] = None,
    launch_id: Optional[str] = None,
) -> str:
    """Register a harness session through the target-aware service client.

    ``launch_id`` names the launch that started this session, when one
    did; registration binds the launching actor from it rather than the
    operating actor of this machine.

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
    if native_thread_id is None:
        from yoke_core.hooks.helpers_identity import detect_native_thread_id

        native_thread_id = detect_native_thread_id(executor, session_id)
    project_id = _project_id_for_root(root)
    if project_id is None:
        return "session registration requires a configured project_id for this checkout"
    if _local_authority_active():
        from yoke_core.hooks.registration import _register_in_process

        return _register_in_process(
            session_id,
            executor,
            provider,
            model_facts,
            root,
            entrypoint,
            project_id=project_id,
            executor_version=executor_version,
            machine_id=machine_id,
            native_thread_id=native_thread_id,
            launch_id=launch_id,
        )
    return service_client.register_session(
        service_client_path(root),
        session_id,
        executor,
        provider,
        model_facts,
        root,
        entrypoint,
        project_id,
        executor_version,
        machine_id,
        native_thread_id,
        launch_id=launch_id,
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


def _local_authority_active() -> bool:
    """Return whether this process owns a non-production Postgres universe."""
    try:
        from yoke_core.domain.machine_config import active_connection
        from yoke_contracts.machine_config.schema import (
            POSTGRES_TRANSPORTS,
            connection_is_prod,
        )

        connection = active_connection()
        transport = str(connection.get("transport") or "")
        return (
            transport in POSTGRES_TRANSPORTS
            and not connection_is_prod(connection)
        )
    except Exception:
        return False


def touch_harness_session(root: str, session_id: str) -> int:
    """Heartbeat a harness session through the target-aware service client."""
    if _local_authority_active():
        try:
            from yoke_core.domain import db_helpers
            from yoke_core.domain.sessions_lifecycle_registry import heartbeat

            conn = db_helpers.connect()
            try:
                heartbeat(conn, session_id)
            finally:
                conn.close()
            return 0
        except Exception:
            return 1
    return service_client.touch_session(service_client_path(root), root, session_id)


def session_begin_recovery_command(
    *,
    root: str,
    session_id: str,
    executor: str,
    provider: str,
    requested_model: str,
    entrypoint: Optional[str] = None,
    executor_version: Optional[str] = None,
    machine_id: Optional[str] = None,
) -> str:
    """Render an operator recovery command for the target-aware service client.

    The recipe names the model as a *request*: an operator re-running
    ``session-begin`` is stating what to run, not reporting what a provider
    served, so the served columns stay unset until an attestation fills them.
    """
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
        "--requested-model",
        requested_model,
        "--workspace",
        root,
    ]
    project_id = _project_id_for_root(root)
    if project_id is not None:
        parts.extend(["--project-id", str(project_id)])
    if entrypoint:
        parts.extend(["--entrypoint", entrypoint])
    if executor_version:
        parts.extend(["--executor-version", executor_version])
    if machine_id:
        parts.extend(["--machine-id", machine_id])
    return " ".join(shlex.quote(part) for part in parts)
