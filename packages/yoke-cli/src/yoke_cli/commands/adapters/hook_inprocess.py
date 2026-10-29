"""Canonical in-process implementation behind resident hook dispatch."""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import sys
from typing import Any, Callable

from yoke_contracts.hook_evaluator_protocol import attach_evaluator_metadata
from yoke_contracts.hook_runner.chain_registry import (
    session_orientation_event,
    session_orientation_redelivery_event,
)


def _touch_detached_resume() -> None:
    """Refresh machine-local custody when this hook belongs to a resume."""
    try:
        from yoke_harness.session_launch_containment import (
            touch_supervised_resume_from_environment,
        )

        touch_supervised_resume_from_environment()
    except Exception:
        return


def evaluate_inprocess(
    event_name: str,
    stdin_data: str,
    *,
    dry_run: bool,
    cursor_invocation: bool,
    http_opener: Callable[..., Any] | None = None,
    evaluator: str = "inprocess",
    warm_duration_ms: int = 0,
    fallback_reason: str = "",
    client_timing_id: str = "",
    on_complete: Callable[[], None] | None = None,
) -> int:
    """Run the existing hook chain after the caller context is established."""
    original_stdin = stdin_data
    if not dry_run:
        _touch_detached_resume()
        stdin_data = attach_evaluator_metadata(
            stdin_data,
            evaluator=evaluator,
            warm_duration_ms=warm_duration_ms,
            fallback_reason=fallback_reason,
            client_timing_id=client_timing_id,
        )
    try:
        from yoke_harness.hooks.relay import (
            evaluate_hook_event,
            relay_hook_event,
        )
    except ImportError as exc:
        if dry_run:
            sys.stderr.write(
                f"yoke hook evaluate --dry-run requires yoke-harness: {exc}\n"
            )
            return 1
        # hook_evaluate turns this into the shared degraded allow.
        raise

    if dry_run:
        return evaluate_hook_event(event_name, dry_run=True, stdin_data=stdin_data)

    from yoke_harness.hooks.command_workdir_stamp import stamp_command_workdir
    from yoke_harness.hooks.identity import detect_executor

    if (
        event_name in {"SessionStart", "UserPromptSubmit"}
        and detect_executor() == "codex"
    ):
        from yoke_harness.hooks.relay_identity_guard import parse_hook_payload
        from yoke_harness.hooks.identity_codex_runtime import codex_transcript_exists

        payload = parse_hook_payload(stdin_data)
        session_id = str(payload.get("session_id") or payload.get("thread_id") or "")
        transcript_path = str(payload.get("transcript_path") or "")
        unsaved = (
            not transcript_path
            if event_name == "SessionStart"
            else session_id and not codex_transcript_exists(session_id, transcript_path)
        )
        if unsaved:
            if on_complete is not None:
                on_complete()
            return 0

    # Every evaluation path — relayed, local universe, local subset — reads
    # the command's workdir from stdin, and only this machine can recover it.
    stdin_data = stamp_command_workdir(stdin_data, detect_executor())

    from yoke_cli.transport.https import TransportError, resolve_https_connection

    try:
        connection = resolve_https_connection()
    except TransportError as exc:
        from yoke_contracts.hook_runner.degraded import infrastructure_reply

        text = infrastructure_reply(
            event_name, detect_executor(), f"hook_authority_unavailable: {exc}"
        )
        if text:
            sys.stdout.write(text)
        return 0

    extra_context = _session_orientation(
        event_name,
        stdin_data,
        cursor=cursor_invocation,
    )

    def evaluate() -> int:
        if connection is not None:
            return relay_hook_event(
                event_name,
                connection,
                stdin_data=stdin_data,
                capture_stdin_data=original_stdin,
                extra_context=extra_context,
                opener=http_opener,
            )
        if _active_local_universe():
            return _evaluate_local_universe_hook(
                event_name,
                stdin_data,
                extra_context=extra_context,
            )
        return evaluate_hook_event(
            event_name,
            stdin_data=stdin_data,
            extra_context=extra_context,
        )

    result = _evaluate_confirming_orientation(evaluate) if extra_context else evaluate()
    if on_complete is not None:
        on_complete()
    return result


def _session_orientation(
    event_name: str,
    stdin_data: str,
    *,
    cursor: bool,
) -> str:
    """Compose this machine's harness-timed session orientation, or ``""``."""
    from yoke_harness.hooks.identity import detect_executor

    if event_name not in (
        session_orientation_event(cursor=cursor, executor=detect_executor()),
        session_orientation_redelivery_event(cursor=cursor),
    ):
        return ""
    try:
        module = importlib.import_module("yoke_core.domain.session_orientation")
    except Exception:
        return ""
    try:
        return (
            module.orientation_for_hook(
                event_name,
                stdin_data,
                cursor=cursor,
            )
            or ""
        )
    except Exception:
        return ""


def _confirm_orientation(printed: str) -> None:
    try:
        module = importlib.import_module("yoke_core.domain.session_orientation")
        envelope = json.loads(printed)
        inner = envelope.get("hookSpecificOutput", {})
        if (
            envelope.get("permission") == "deny"
            or envelope.get("decision") == "block"
            or inner.get("permissionDecision") == "deny"
        ):
            return
        body = envelope.get("additional_context")
        if body is None:
            body = envelope.get("hookSpecificOutput", {}).get("additionalContext")
        if isinstance(body, str) and module.ORIENTATION_HEADING in body:
            module.confirm_orientation_delivery(body)
    except Exception:
        pass


def _evaluate_confirming_orientation(evaluate: Callable[[], int]) -> int:
    """Retire an orientation only after this request actually printed it."""
    try:
        from yoke_contracts.hook_process_context import active_output_capture

        capture = active_output_capture()
    except Exception:
        capture = None
    exit_code = None
    if capture is not None:
        mark = capture.stdout_mark()
        try:
            exit_code = evaluate()
            return exit_code
        finally:
            if exit_code == 0:
                _confirm_orientation(capture.stdout_since(mark))

    buffered = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffered):
            exit_code = evaluate()
            return exit_code
    finally:
        printed = buffered.getvalue()
        if printed:
            sys.stdout.write(printed)
        if exit_code == 0:
            _confirm_orientation(printed)


def _active_local_universe() -> bool:
    """Return whether the active connection is non-production Postgres."""
    try:
        from yoke_cli.config import machine_config
        from yoke_contracts.machine_config.schema import (
            POSTGRES_TRANSPORTS,
            connection_is_protected,
        )

        connection = machine_config.active_connection()
    except Exception:
        return False
    transport = str(connection.get("transport") or "").strip()
    return transport in POSTGRES_TRANSPORTS and not connection_is_protected(connection)


def _evaluate_local_universe_hook(
    event_name: str,
    stdin_data: str,
    *,
    extra_context: str,
) -> int:
    """Load the installed engine hook entry and fail loudly if it is absent."""
    try:
        module = importlib.import_module("yoke_core.hooks.local_entry")
    except (ImportError, ModuleNotFoundError) as exc:
        sys.stderr.write(
            "ERROR: YOKE_LOCAL_HOOK_ENGINE_MISSING: the active "
            f"local-postgres universe requires yoke-core hooks ({exc})\n"
        )
        return 1
    try:
        return int(
            module.evaluate_local_hook(
                event_name,
                stdin_data,
                extra_context=extra_context,
            )
        )
    except Exception as exc:
        sys.stderr.write(
            f"ERROR: YOKE_LOCAL_HOOK_ENGINE_FAILED: {type(exc).__name__}: {exc}\n"
        )
        return 1


__all__ = ["evaluate_inprocess"]
