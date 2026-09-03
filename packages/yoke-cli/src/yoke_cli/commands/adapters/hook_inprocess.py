"""Canonical in-process implementation behind resident hook dispatch."""

from __future__ import annotations

import contextlib
import importlib
import io
import sys
from typing import Any, Callable

from yoke_contracts.hook_evaluator_protocol import attach_evaluator_metadata
from yoke_contracts.hook_runner.chain_registry import (
    session_orientation_event,
    session_orientation_redelivery_event,
)
from yoke_contracts.hook_runner.cursor_response import (
    cursor_lifecycle_allow_stdout,
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


def _degrade_to_noop(
    event_name: str,
    detail: str,
    *,
    cursor_invocation: bool,
) -> int:
    sys.stderr.write(
        f"WARNING: YOKE_HOOK_DEGRADED: yoke hook evaluate {event_name}: "
        "yoke-harness unavailable; "
        f"degraded to no-op allow ({detail})\n"
    )
    if cursor_invocation:
        stdout = cursor_lifecycle_allow_stdout(event_name)
        if stdout:
            sys.stdout.write(stdout)
    return 0


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
) -> int:
    """Run the existing hook chain after the caller context is established."""
    if not dry_run:
        _touch_detached_resume()
        stdin_data = attach_evaluator_metadata(
            stdin_data,
            evaluator=evaluator,
            warm_duration_ms=warm_duration_ms,
            fallback_reason=fallback_reason,
        )
    try:
        from yoke_harness.hooks.relay import (
            degrade_to_noop,
            evaluate_hook_event,
            relay_hook_event,
        )
    except ImportError as exc:
        if dry_run:
            sys.stderr.write(
                f"yoke hook evaluate --dry-run requires yoke-harness: {exc}\n"
            )
            return 1
        return _degrade_to_noop(
            event_name,
            str(exc),
            cursor_invocation=cursor_invocation,
        )

    if dry_run:
        return evaluate_hook_event(event_name, dry_run=True)

    from yoke_cli.transport.https import TransportError, resolve_https_connection

    try:
        connection = resolve_https_connection()
    except TransportError as exc:
        return degrade_to_noop(event_name, str(exc))

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

    if not extra_context:
        return evaluate()
    return _evaluate_confirming_orientation(evaluate)


def _session_orientation(
    event_name: str,
    stdin_data: str,
    *,
    cursor: bool,
) -> str:
    """Compose this machine's harness-timed session orientation, or ``""``."""
    if event_name not in (
        session_orientation_event(cursor=cursor),
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
        if module.ORIENTATION_HEADING in printed:
            module.confirm_orientation_delivery()
    except Exception:
        pass


def _evaluate_confirming_orientation(evaluate: Callable[[], int]) -> int:
    """Retire an orientation only after this request actually printed it."""
    try:
        from yoke_contracts.hook_process_context import active_output_capture

        capture = active_output_capture()
    except Exception:
        capture = None
    if capture is not None:
        mark = capture.stdout_mark()
        try:
            return evaluate()
        finally:
            _confirm_orientation(capture.stdout_since(mark))

    buffered = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffered):
            return evaluate()
    finally:
        printed = buffered.getvalue()
        if printed:
            sys.stdout.write(printed)
        _confirm_orientation(printed)


def _active_local_universe() -> bool:
    """Return whether the active connection is non-production Postgres."""
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
    return transport in POSTGRES_TRANSPORTS and not connection_is_prod(connection)


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
