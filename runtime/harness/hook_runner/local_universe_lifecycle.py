"""In-process session lifecycle for a bound local-postgres universe.

The hook relay (``yoke_harness.hooks``) is a thin client that must not reach
the engine: on https it relays to the server (which registers/heartbeats/ends
against the connected authority) and on any other transport it runs only the
client-local lint subset. That leaves a gap on a genuine local-postgres
universe, where the CLIENT *is* the authority: a session that never runs
``/yoke do`` gets lints but no ``harness_sessions`` row, no heartbeat, and no
end cleanup.

This engine-side orchestrator closes that gap. Driven from the ``yoke hook
evaluate`` CLI adapter (which reaches the engine in-process, exactly as the
function-call dispatcher does for a local universe), it mirrors what the
server does for a relayed event — but against the client's own local
universe:

- SessionStart / UserPromptSubmit / Pre|PostToolUse -> ensure a session row
  exists (register on first sight) and heartbeat it.
- SessionStart -> also reap stale sessions.
- Stop / SessionEnd -> run the bounded end cleanup.

Guardrails: gated on an ACTIVE non-prod local-postgres connection (no
universe bound, https, or prod-postgres -> no-op, current behavior kept);
never raises (a registration failure must never affect the hook decision);
the lint subset is unaffected (the adapter runs it independently and owns the
verdict). Registration reuses ``begin_session`` — the same routing-config +
``SESSION_EXISTS`` idempotency path ``/yoke do`` uses — so a later
``sessions.begin`` on the same session converges with no duplicate row.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional, Tuple

__all__ = ["run_local_universe_session_lifecycle", "local_universe_active"]


def _parse_payload(stdin_data: str) -> dict:
    try:
        payload = json.loads(stdin_data) if stdin_data else None
    except (json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def local_universe_active() -> bool:
    """True only when the active connection is a bound non-prod local-postgres
    universe. https (relay owns registration), prod-postgres (operator-only),
    no universe bound, or any config-read failure resolve False so the current
    lint-only / relay behavior is untouched."""
    try:
        from yoke_cli.transport.https import resolve_https_connection

        if resolve_https_connection() is not None:
            return False
    except Exception:
        return False
    try:
        from yoke_cli.config import machine_config
        from yoke_contracts.machine_config.schema import (
            POSTGRES_TRANSPORTS,
            connection_is_prod,
        )

        connection = machine_config.active_connection()
    except Exception:
        return False
    transport = str(connection.get("transport") or "").strip()
    if transport not in POSTGRES_TRANSPORTS:
        return False
    return not connection_is_prod(connection)


def _resolve_project(payload: dict) -> Tuple[Optional[int], str]:
    """Resolve (project_id, workspace) client-side from the checkout map.

    Mirrors how ``session_init`` / ``sessions.begin`` resolve project identity
    (the checkout->project machine-config map). Returns ``(None, workspace)``
    when the checkout is not project-mapped, so a non-Yoke-target checkout
    no-ops rather than registering."""
    try:
        from yoke_cli.config import machine_config
        from yoke_cli.config.checkout_context import resolve_repo_root_from_cwd

        repo_root = resolve_repo_root_from_cwd()
        cwd = payload.get("cwd")
        workspace = repo_root or (cwd if isinstance(cwd, str) and cwd else os.getcwd())
        if not repo_root:
            return None, workspace
        return machine_config.project_id(repo_root), str(workspace)
    except Exception:
        cwd = payload.get("cwd")
        return None, cwd if isinstance(cwd, str) and cwd else os.getcwd()


def _register(conn, session_id: str, payload: dict, project_id: int, workspace: str) -> None:
    """Record the process anchor and register via ``begin_session``.

    ``begin_session`` is the same real-routing-config + ``SESSION_EXISTS``
    idempotency path ``/yoke do`` drives, so the local hook registration and a
    later ``sessions.begin`` converge on one row."""
    from runtime.harness.hook_helpers import (
        detect_entrypoint,
        detect_executor,
        detect_model,
        detect_provider,
    )
    from yoke_core.api.service_client_sessions_lifecycle_begin import begin_session
    from yoke_core.domain.session_process_anchors import record_session_anchor

    executor = detect_executor()
    provider = detect_provider(executor)
    transcript_path = payload.get("transcript_path")
    transcript_path = transcript_path if isinstance(transcript_path, str) else ""
    payload_model = payload.get("model")
    model = (
        payload_model
        if isinstance(payload_model, str) and payload_model
        else detect_model(executor, transcript_path=transcript_path)
    )
    payload_entrypoint = payload.get("entrypoint")
    entrypoint = (
        payload_entrypoint
        if isinstance(payload_entrypoint, str) and payload_entrypoint
        else detect_entrypoint()
    )
    record_session_anchor(session_id, transcript_path=transcript_path)
    begin_session(
        conn,
        session_id=session_id,
        executor=executor,
        provider=provider,
        model=model,
        workspace=workspace,
        project_id=project_id,
        entrypoint=entrypoint,
    )


def _ensure_registered_and_heartbeat(session_id: str, payload: dict) -> None:
    from yoke_core.domain.db_backend import connect
    from yoke_core.domain.sessions import SessionError
    from yoke_core.domain.sessions_lifecycle_registry import heartbeat

    project_id, workspace = _resolve_project(payload)
    conn = connect()
    try:
        try:
            heartbeat(conn, session_id)
        except SessionError as exc:
            if exc.code not in ("NOT_FOUND", "SESSION_ENDED"):
                return
            if project_id is None:
                return  # not a project-mapped checkout; cannot register
            _register(conn, session_id, payload, project_id, workspace)
            try:
                heartbeat(conn, session_id)
            except SessionError:
                return
    finally:
        conn.close()


def _end_cleanup(session_id: str, event_name: str) -> None:
    from runtime.harness.hook_helpers import detect_executor
    from runtime.harness.hook_runner.session_end_cleanup import (
        run_session_end_cleanup_in_process,
    )

    run_session_end_cleanup_in_process(
        session_id, executor=detect_executor(), event_source=event_name,
    )


def _stale_reap() -> None:
    from yoke_core.domain.db_backend import connect
    from yoke_core.domain.sessions_cleanup import clean_stale_harness_sessions

    conn = connect()
    try:
        clean_stale_harness_sessions(conn)
    finally:
        conn.close()


def run_local_universe_session_lifecycle(event_name: str, stdin_data: str) -> None:
    """Drive the in-process session lifecycle for one hook event against a
    bound local universe. No-op unless a non-prod local-postgres universe is
    active. Never raises — a lifecycle failure must never affect the hook."""
    try:
        if not local_universe_active():
            return
        payload = _parse_payload(stdin_data)
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id or session_id == "unknown":
            return
        if event_name in ("Stop", "SessionEnd"):
            _end_cleanup(session_id, event_name)
            return
        if event_name in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"):
            _ensure_registered_and_heartbeat(session_id, payload)
        if event_name == "SessionStart":
            _stale_reap()
    except Exception:
        return
