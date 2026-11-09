"""Best-effort telemetry for failed session hook execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from yoke_contracts.project_defaults import default_project_for_directory


def emit_session_hook_failed(
    *,
    hook_event: str,
    executor: str,
    reason: str,
    latency_ms: int,
    stdin_state: str,
    session_id_source: str,
    session_id: str = "",
    service_client_path: str = "",
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """Emit a ``HarnessSessionHookFailed`` event via the native Python emitter.

    Non-fatal: any exception is swallowed so that the hook path cannot itself
    crash the harness close sequence.
    """
    context: dict[str, Any] = {
        "hook_event": hook_event,
        "executor": executor,
        "reason": reason,
        "latency_ms": int(latency_ms),
        "stdin_state": stdin_state,
        "session_id_source": session_id_source,
    }
    if service_client_path:
        context["service_client_path"] = service_client_path
    if extra:
        context.update(extra)

    try:
        from yoke_core.domain.events import emit_event as _emit

        _emit(
            "HarnessSessionHookFailed",
            event_kind="system",
            event_type="session_hook_failure",
            source_type="hook",
            session_id=session_id or "unknown",
            severity="WARN",
            outcome="failed",
            project=default_project_for_directory(Path.cwd()),
            hook_event_name=hook_event,
            context=context,
        )
    except Exception:
        return
