"""Telemetry surface for the shared hook runner.

Re-exports the public callables every lint/guardrail consumer reaches
for via ``runtime.harness.hook_runner.telemetry`` and adds three
runner-native emitters (``HookGuardrailEvaluated`` /
``HookExecutionFailed`` / ``HookDispatchTelemetry``) that the dispatch
core fires once per chain step.

Same-object semantics matter: callers do
``mock.patch("runtime.harness.hook_runner.telemetry.X", ...)`` and
expect that to take effect at every call site. A wrapper function
would break that contract; module-level re-export aliases preserve it.

Sibling owners:

- :mod:`runtime.harness.hook_runner.denial` — denial-event payload
  builders and the ``HarnessToolCallDenied`` emitter.
- :mod:`runtime.harness.hook_runner.identity` — session-identity
  resolution, env-file persistence, telemetry classification.
- :mod:`runtime.harness.hook_runner.service_client` — repo-root
  resolution, ``service_client.py`` path lookup, ``register_session``
  driver, and the post-turn model refresh
  (``refresh_session_model_if_placeholder``).
- :mod:`runtime.harness.hook_runner.stdin` — bounded stdin reads and
  the ``HarnessSessionHookFailed`` /
  ``HarnessSessionSentFirstUserPromptSubmit`` emitters.
"""

from __future__ import annotations

from typing import Any, Optional

from runtime.harness.hook_runner.denial import (  # noqa: F401
    COMMAND_SNIPPET_MAX_BYTES,
    build_denial_context,
    build_denial_payload,
    emit_denial_event,
)
from runtime.harness.hook_runner.identity import (  # noqa: F401
    _classify_session_id_source,
    persist_session_id_to_env_file,
    resolve_direct_session_id,
    resolve_env_init_session_id,
    resolve_session_id_from_env_and_payload,
)
from runtime.harness.hook_runner.service_client import (  # noqa: F401
    refresh_session_model_if_placeholder,
    register_session,
    resolve_repo_root,
    session_service_client_path,
)
from runtime.harness.hook_runner.stdin import (  # noqa: F401
    STDIN_FALLBACK_MAX_BYTES,
    STDIN_FALLBACK_TIMEOUT_SECONDS,
    bounded_stdin_read,
    emit_harness_session_sent_first_user_prompt_submit,
    emit_session_hook_failed,
)


def _emit_hook_event(
    event_name: str,
    *,
    event_type: str,
    severity: str,
    outcome: str,
    module: str,
    hook_event: str,
    executor: str,
    session_id: str = "",
    item_id: Optional[int] = None,
    tool_name: str = "",
    duration_ms: Optional[int] = None,
    extra: Optional[dict[str, Any]] = None,
    conn: Optional[Any] = None,
) -> None:
    """Best-effort runner-event emission. Telemetry must never propagate.

    ``conn`` lets a batched flush reuse one connection across many rows; when
    ``None`` the underlying emitter opens its own short-lived connection.
    """
    context: dict[str, Any] = {
        "module": module,
        "hook_event": hook_event,
        "executor": executor,
    }
    if extra:
        context.update(extra)
    try:
        from yoke_core.domain.events import emit_event as _emit

        _emit(
            event_name,
            event_kind="system",
            event_type=event_type,
            source_type="hook",
            session_id=session_id or "unknown",
            severity=severity,
            outcome=outcome,
            project="yoke",
            item_id=str(item_id) if item_id is not None else None,
            tool_name=tool_name or None,
            hook_event_name=hook_event,
            duration_ms=duration_ms,
            context=context,
            conn=conn,
        )
    except Exception:
        return


def emit_hook_guardrail_evaluated(
    *,
    module: str,
    hook_event: str,
    executor: str,
    decision_outcome: str,
    session_id: str = "",
    item_id: Optional[int] = None,
    tool_name: str = "",
    duration_ms: Optional[int] = None,
    extra: Optional[dict[str, Any]] = None,
    conn: Optional[Any] = None,
) -> None:
    """Emit a ``HookGuardrailEvaluated`` event for a completed chain step.

    Severity DEBUG: this per-chain-step "module evaluated -> outcome" row is
    the highest-volume event in the system (~71% of the events table) and its
    steady-state signal is fully redundant — the per-invocation aggregate lives
    in ``HookDispatchTelemetry`` (chain_length + final decision_outcome +
    duration_ms) and denials/failures live in ``HarnessToolCallDenied`` /
    ``HookExecutionFailed`` (WARN, 90d retention). At the default INFO write
    floor these are dropped at insert time; lower ``severity_config`` to DEBUG
    (globally or via a per-event override) to capture per-module lint detail
    on demand for a debugging session.
    """
    payload = dict(extra or {})
    payload["decision_outcome"] = decision_outcome
    _emit_hook_event(
        "HookGuardrailEvaluated",
        event_type="hook_guardrail_evaluated",
        severity="DEBUG",
        outcome="completed",
        module=module,
        hook_event=hook_event,
        executor=executor,
        session_id=session_id,
        item_id=item_id,
        tool_name=tool_name,
        duration_ms=duration_ms,
        extra=payload,
        conn=conn,
    )


def emit_hook_execution_failed(
    *,
    module: str,
    hook_event: str,
    executor: str,
    failure: str,
    session_id: str = "",
    item_id: Optional[int] = None,
    tool_name: str = "",
    duration_ms: Optional[int] = None,
    extra: Optional[dict[str, Any]] = None,
    conn: Optional[Any] = None,
) -> None:
    """Emit a ``HookExecutionFailed`` event when a chain step crashes/times out."""
    payload = dict(extra or {})
    payload["failure"] = failure
    _emit_hook_event(
        "HookExecutionFailed",
        event_type="hook_execution_failure",
        severity="WARN",
        outcome="failed",
        module=module,
        hook_event=hook_event,
        executor=executor,
        session_id=session_id,
        item_id=item_id,
        tool_name=tool_name,
        duration_ms=duration_ms,
        extra=payload,
        conn=conn,
    )


def emit_hook_dispatch_telemetry(
    *,
    hook_event: str,
    executor: str,
    chain_length: int,
    decision_outcome: str,
    session_id: str = "",
    item_id: Optional[int] = None,
    tool_name: str = "",
    duration_ms: Optional[int] = None,
    extra: Optional[dict[str, Any]] = None,
    conn: Optional[Any] = None,
) -> None:
    """Emit a ``HookDispatchTelemetry`` event summarizing one runner invocation."""
    payload = dict(extra or {})
    payload["chain_length"] = int(chain_length)
    payload["decision_outcome"] = decision_outcome
    _emit_hook_event(
        "HookDispatchTelemetry",
        event_type="hook_dispatch",
        severity="INFO",
        outcome="completed",
        module="runtime.harness.hook_runner",
        hook_event=hook_event,
        executor=executor,
        session_id=session_id,
        item_id=item_id,
        tool_name=tool_name,
        duration_ms=duration_ms,
        extra=payload,
        conn=conn,
    )


# (event_name, severity) each emitter hands to _emit_hook_event, keyed by the
# record ``kind`` the runner accumulates. Lets the flush resolve each event's
# severity floor once and drop the high-volume throwaway rows (DEBUG guardrail
# rows the default INFO floor discards) before any DB round-trip. Mirror of the
# literals in the three emitters above; the severity-skip test pins them.
_KIND_EVENT_SEVERITY = {
    "guardrail": ("HookGuardrailEvaluated", "DEBUG"),
    "failed": ("HookExecutionFailed", "WARN"),
    "dispatch": ("HookDispatchTelemetry", "INFO"),
}
_HOOK_SOURCE_TYPE = "hook"


def flush_hook_telemetry(records, *, deadline=None, ensure_session=None) -> None:
    """Flush accumulated hook-telemetry records over ONE reused connection.

    ``records`` is the runner's ordered ``(kind, kwargs)`` list
    (``"guardrail"`` / ``"failed"`` / ``"dispatch"``). Emitting after
    the dispatch loop keeps per-module DB latency off the deadline; one
    reused connection collapses N cold connects into one.

    ``ensure_session`` — optional ``(session_id, payload_json,
    transcript_path, record_anchor, executor_hint, register_in_process,
    force_reregister, actor_id, project_id)`` — arms
    ensure-register-on-first-sight:
    the row is probed on the shared connection BEFORE the records flush;
    a missing row drives ``_register_from_hook``, so tool-call hooks are
    a registration path and the first dispatch's rows enrich fresh.
    ``actor_id`` is the server-verified bearer-token actor (None locally).

    Best-effort: never raises. A supplied ``deadline`` stops emission at
    budget exhaustion. Emitters resolve at call time so test patches
    still intercept.
    """
    if not records and ensure_session is None:
        return
    emitters = {
        "guardrail": emit_hook_guardrail_evaluated,
        "failed": emit_hook_execution_failed,
        "dispatch": emit_hook_dispatch_telemetry,
    }
    try:
        from yoke_core.domain.events_writes import (
            check_severity_conn,
            hook_emit_connection,
        )
    except Exception:  # noqa: BLE001 — degrade to per-call connections, no skip
        _flush_records(records, emitters, conn=None, severity_check=None, deadline=deadline)
        return
    with hook_emit_connection() as conn:
        if ensure_session is not None and conn is not None:
            try:  # register-if-missing; the net must never break dispatch
                from runtime.harness.hook_runner_register import (
                    ensure_registered_from_hook,
                )

                (session_id, payload_json, transcript_path, record_anchor,
                 executor_hint, in_process, force, actor_id,
                 project_id) = ensure_session
                ensure_registered_from_hook(
                    conn, payload_json, session_id,
                    transcript_path=transcript_path,
                    record_anchor=record_anchor,
                    executor_hint=executor_hint,
                    register_in_process=in_process,
                    force_reregister=force, actor_id=actor_id,
                    project_id=project_id,
                )
            except Exception:  # noqa: BLE001
                pass
        check = check_severity_conn if conn is not None else None
        _flush_records(records, emitters, conn=conn, severity_check=check, deadline=deadline)


def _flush_records(records, emitters, *, conn, severity_check, deadline) -> None:
    """Invoke each record's emitter over the shared ``conn``; budget-gated.

    Skip-the-throwaway: when ``severity_check`` is available, resolve each
    event name's floor once (cached per kind) and drop sub-floor rows before
    any DB round-trip — so the high-volume DEBUG guardrail rows the default
    INFO floor discards never reach the writer. Keepers flow through the
    emitter over the shared connection.
    """
    floor_ok: dict[str, bool] = {}
    for kind, kwargs in records:
        if deadline is not None and not deadline.telemetry_allowed():
            return
        emitter = emitters.get(kind)
        if emitter is None:
            continue
        name_sev = _KIND_EVENT_SEVERITY.get(kind)
        if severity_check is not None and name_sev is not None:
            ok = floor_ok.get(kind)
            if ok is None:
                try:
                    ok = severity_check(conn, name_sev[0], _HOOK_SOURCE_TYPE, name_sev[1])
                except Exception:  # noqa: BLE001 — a probe failure must not drop the row
                    ok = True
                floor_ok[kind] = ok
            if not ok:
                continue  # throwaway: below the configured floor, skip the write
        try:
            emitter(conn=conn, **kwargs)
        except Exception:  # noqa: BLE001 — one bad row must not drop the rest
            continue


__all__ = [
    "COMMAND_SNIPPET_MAX_BYTES",
    "STDIN_FALLBACK_MAX_BYTES",
    "STDIN_FALLBACK_TIMEOUT_SECONDS",
    "_classify_session_id_source",
    "bounded_stdin_read",
    "build_denial_context",
    "build_denial_payload",
    "emit_denial_event",
    "emit_harness_session_sent_first_user_prompt_submit",
    "emit_hook_dispatch_telemetry",
    "emit_hook_execution_failed",
    "emit_hook_guardrail_evaluated",
    "emit_session_hook_failed",
    "flush_hook_telemetry",
    "persist_session_id_to_env_file",
    "refresh_session_model_if_placeholder",
    "register_session",
    "resolve_direct_session_id",
    "resolve_env_init_session_id",
    "resolve_repo_root",
    "resolve_session_id_from_env_and_payload",
    "session_service_client_path",
]
