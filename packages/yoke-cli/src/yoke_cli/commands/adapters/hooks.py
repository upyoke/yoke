"""``yoke hook evaluate`` adapter.

Project hook configs keep this one spelling on every transport. The product
adapter uses ``yoke_harness`` for client-only evaluation and dispatches the
complete packaged chain through ``yoke_core`` when a local Postgres universe
is active. Missing local engine code is a permanent install defect and fails
loudly; transient HTTPS transport failures retain their fail-open contract.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Callable, List

from yoke_contracts.field_note_text import FOOTER as _FIELD_NOTE_FOOTER
from yoke_contracts.hook_runner.chain_registry import (
    session_orientation_event,
    session_orientation_redelivery_event,
)
from yoke_contracts.hook_runner.config_owner import (
    CONFIG_OWNER_ENV_VAR,
)
from yoke_contracts.hook_runner.cursor_response import (
    cursor_lifecycle_allow_stdout,
)
from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.commands.adapters.hook_config_dedup import (
    is_cursor_config_invocation,
    should_skip_config_duplicate,
)


__all__ = ["HOOK_EVALUATE_USAGE", "hook_evaluate"]


HOOK_EVALUATE_USAGE = "yoke hook evaluate <event> [--dry-run]"


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


def hook_evaluate(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke hook evaluate",
        description=HOOK_EVALUATE_USAGE,
        epilog=_FIELD_NOTE_FOOTER,
    )
    parser.add_argument(
        "event_name",
        help="Hook event name (for example PreToolUse, PostToolUse, Stop).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the ordered hook chain and exit.",
    )
    parsed = parse_or_usage_error(parser, args, HOOK_EVALUATE_USAGE)
    if parsed is None:
        return 2
    if not parsed.dry_run:
        _touch_detached_resume()

    stdin_data = None
    cursor_invocation = is_cursor_config_invocation(os.environ, "")
    if not parsed.dry_run and os.environ.get(CONFIG_OWNER_ENV_VAR):
        # Owner-marked compatibility/backstop hooks need both process and
        # payload provenance before deduplication. Read once here so an
        # ambient Cursor variable cannot disable a genuine Claude hook.
        stdin_data = sys.stdin.read()
        cursor_invocation = cursor_invocation or is_cursor_config_invocation(
            os.environ, stdin_data
        )
        if should_skip_config_duplicate(
            parsed.event_name,
            os.environ,
            stdin_data,
        ):
            stdout = cursor_lifecycle_allow_stdout(parsed.event_name)
            if stdout:
                sys.stdout.write(stdout)
            return 0

    try:
        from yoke_harness.hooks.relay import (
            degrade_to_noop,
            evaluate_hook_event,
            relay_hook_event,
        )
    except ImportError as exc:
        if parsed.dry_run:
            sys.stderr.write(
                f"yoke hook evaluate --dry-run requires yoke-harness: {exc}\n"
            )
            return 1
        return _degrade_to_noop(
            parsed.event_name,
            str(exc),
            cursor_invocation=cursor_invocation,
        )

    if not parsed.dry_run:
        from yoke_cli.transport.https import (
            TransportError,
            resolve_https_connection,
        )

        try:
            connection = resolve_https_connection()
        except TransportError as exc:
            # Half-configured https: other CLI surfaces fail loudly, but a
            # hook must never block the harness on transport config. An
            # owner-marked config has already supplied stdin for provenance.
            return degrade_to_noop(parsed.event_name, str(exc))

        # Read stdin once: the relay, the orientation composer, and the
        # local engine all need the same payload, and a hook process gets
        # exactly one shot at it.
        if stdin_data is None:
            stdin_data = sys.stdin.read()
        extra_context = _session_orientation(
            parsed.event_name,
            stdin_data,
            cursor=cursor_invocation,
        )

        def evaluate() -> int:
            if connection is not None:
                return relay_hook_event(
                    parsed.event_name,
                    connection,
                    stdin_data=stdin_data,
                    extra_context=extra_context,
                )
            # A bound local-postgres universe is an installed engine
            # authority, so run the complete packaged chain in-process.
            # Machines with no bound universe retain the product-safe
            # client subset.
            if _active_local_universe():
                return _evaluate_local_universe_hook(
                    parsed.event_name,
                    stdin_data,
                    extra_context=extra_context,
                )
            return evaluate_hook_event(
                parsed.event_name,
                stdin_data=stdin_data,
                extra_context=extra_context,
            )

        if not extra_context:
            return evaluate()
        return _evaluate_confirming_orientation(evaluate)

    return evaluate_hook_event(parsed.event_name, dry_run=parsed.dry_run)


def _session_orientation(
    event_name: str,
    stdin_data: str,
    *,
    cursor: bool,
) -> str:
    """Compose this machine's harness-timed session orientation, or ``""``.

    Reaches the engine-side composer (bundled with the core wheel) through
    the sanctioned dynamic-import lane, for the same reason the local
    hook entry does: the client cannot take static authority over
    engine modules before the transport decision. Absent engine -> no
    orientation; never raises, because a hook must not break its agent.

    The event check comes first so every other event — including the hot
    PreToolUse path that fires on every tool call — returns without
    touching the engine at all."""
    import importlib

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


def _evaluate_confirming_orientation(evaluate: Callable[[], int]) -> int:
    """Run *evaluate*, retiring the session's orientation only once printed.

    Composing the block is not delivering it. A deny prints its own message
    in place of the merged allow stdout — on Cursor and Codex with an
    allow's exit code, so the exit status cannot stand in for this — and a
    hook the harness kills on its own timeout prints nothing at all. Holding
    the evaluation's stdout is what lets this process report on what it
    actually printed; the text passes through unchanged, and an unconfirmed
    block is what the next context-bearing event re-delivers.
    """
    import contextlib
    import importlib
    import io

    buffered = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffered):
            return evaluate()
    finally:
        printed = buffered.getvalue()
        if printed:
            sys.stdout.write(printed)
        try:
            module = importlib.import_module("yoke_core.domain.session_orientation")
            if module.ORIENTATION_HEADING in printed:
                module.confirm_orientation_delivery()
        except Exception:
            pass


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
    import importlib

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
