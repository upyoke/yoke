"""``yoke hook evaluate`` adapter.

Project hook configs keep this one spelling on every transport. The product
adapter delegates hook evaluation to ``yoke_harness`` when that package is
installed. Missing harness code fails open for live hook events, because hook
delivery must not break the calling agent; dry-run reports the missing package
clearly instead.
"""

from __future__ import annotations

import argparse
import sys
from typing import List

from yoke_contracts.field_note_text import FOOTER as _FIELD_NOTE_FOOTER
from yoke_cli.commands._helpers import parse_or_usage_error


__all__ = ["HOOK_EVALUATE_USAGE", "hook_evaluate"]


HOOK_EVALUATE_USAGE = (
    "yoke hook evaluate <event> [--dry-run]"
)


def _degrade_to_noop(event_name: str, detail: str) -> int:
    sys.stderr.write(
        f"yoke hook evaluate {event_name}: yoke-harness unavailable; "
        f"degraded to no-op allow ({detail})\n"
    )
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

    try:
        from yoke_harness.hooks.relay import (
            degrade_to_noop,
            evaluate_hook_event,
            relay_hook_event,
        )
    except ImportError as exc:
        if parsed.dry_run:
            sys.stderr.write(
                "yoke hook evaluate --dry-run requires yoke-harness: "
                f"{exc}\n"
            )
            return 1
        return _degrade_to_noop(parsed.event_name, str(exc))

    if not parsed.dry_run:
        import sys

        from yoke_cli.transport.https import (
            TransportError,
            resolve_https_connection,
        )

        try:
            connection = resolve_https_connection()
        except TransportError as exc:
            # Half-configured https: other CLI surfaces fail loudly, but a
            # hook must never block the harness on transport config.
            return degrade_to_noop(parsed.event_name, str(exc))
        if connection is not None:
            return relay_hook_event(parsed.event_name, connection)

        # No https connection. Run the client-local lint subset for the
        # verdict (unchanged), then — only on a bound local-postgres universe
        # where the client IS the authority — drive the in-process session
        # lifecycle (register/heartbeat/end) against it. Fail-open: a
        # lifecycle failure never affects the hook decision, and a machine
        # with no engine / no universe stays lint-only.
        stdin_data = sys.stdin.read()
        exit_code = evaluate_hook_event(
            parsed.event_name, stdin_data=stdin_data,
        )
        _drive_local_universe_lifecycle(parsed.event_name, stdin_data)
        return exit_code

    return evaluate_hook_event(parsed.event_name, dry_run=parsed.dry_run)


def _drive_local_universe_lifecycle(event_name: str, stdin_data: str) -> None:
    """Best-effort in-process session lifecycle for a bound local universe.

    Reaches the engine-side orchestrator (bundled with the core wheel) via the
    sanctioned dynamic-import lane, exactly as the function-call dispatcher
    lazily reaches the engine for a local universe. Absent engine / no
    universe -> no-op; never raises."""
    import importlib

    try:
        module = importlib.import_module(
            "runtime.harness.hook_runner.local_universe_lifecycle"
        )
    except Exception:
        return
    try:
        module.run_local_universe_session_lifecycle(event_name, stdin_data)
    except Exception:
        return
