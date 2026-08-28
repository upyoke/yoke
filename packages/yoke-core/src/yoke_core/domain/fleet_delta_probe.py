"""Poll fleet state and print one line per change.

This is the command the ``yoke watch fleet`` wrapper runs. It has no
Yoke-side dependency on any harness: it reads registered functions,
compares consecutive observations, and writes delta lines to stdout.
Whether those lines become Claude ``Monitor`` wake events, Codex PTY
output, or a scrollback the operator reads afterwards is the caller's
concern, not this loop's.

The steerer's own session id comes from ambient identity, so the same
command survives a steering handoff without being edited.

Silence is the design. A pass where nothing moved prints nothing at
all, which is why the loop is bounded by ``--duration`` rather than
running forever: a bounded run always writes its watcher exit sentinel,
and a follower armed against it always terminates.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable, Sequence, TextIO

from yoke_core.domain.fleet_delta_alarms import DeltaState
from yoke_core.domain.fleet_delta_lines import compare, error_line, fatal_line
from yoke_core.domain.fleet_delta_snapshot import (
    FleetReadError,
    FleetSnapshot,
    read_snapshot,
)

DEFAULT_INTERVAL_SECONDS = 60
DEFAULT_DURATION_SECONDS = 3600
#: Consecutive failed passes before the probe stops instead of looping
#: silently against a control plane it cannot reach.
MAX_CONSECUTIVE_READ_FAILURES = 3
READ_FAILURE_EXIT = 1

HELP_EPILOG = """\
Each pass reads `sessions.list`, `charge.schedule`, and the durable
message listing, then prints one line per change. A pass that observes
no change prints nothing.

Line shapes:
  fleet item YOK-N status <old> -> <new>
  fleet session <id8> registered|ended|terminated surface=<surface>
  fleet inbox <id8> state=pending|injected from=<id8>
  fleet ALARM idle-holder|unowned-item|starved-envelope ...
  fleet CLEAR <alarm-kind> <subject>

examples:
  yoke watch fleet -- --project yoke
  yoke watch fleet -- --project yoke --project platform --interval 30
  yoke watch fleet --print-streaming-pair -- --project yoke
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def dispatch_call(function_id: str, payload: dict[str, Any]) -> Any:
    """Call one registered read over the session's active transport."""
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        build_actor,
        call_dispatcher,
    )

    return call_dispatcher(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        actor=build_actor(),
    )


def ambient_session_id() -> str:
    """Resolve the calling session id from ambient harness identity."""
    from yoke_core.api.service_client_structured_api_adapter import build_actor

    return build_actor().session_id or ""


def run(
    projects: Sequence[str],
    *,
    interval: float = DEFAULT_INTERVAL_SECONDS,
    duration: float = DEFAULT_DURATION_SECONDS,
    out: TextIO | None = None,
    call: Callable[[str, dict[str, Any]], Any] = dispatch_call,
    clock: Callable[[], datetime] = _now,
    sleep: Callable[[float], None] = time.sleep,
    session_id: str | None = None,
) -> int:
    """Poll until *duration* elapses, printing one line per change.

    ``call``, ``clock``, and ``sleep`` are seams so the loop is testable
    without a control plane and without wall-clock waiting.
    """
    stream = out if out is not None else sys.stdout
    resolved_session = (
        session_id if session_id is not None else ambient_session_id()
    )
    state = DeltaState()
    previous: FleetSnapshot | None = None
    consecutive_failures = 0
    started = clock()

    while True:
        # One clock reading per pass: the observation, the alarm ages
        # computed from it, and the duration check all describe the same
        # instant, so a slow pass cannot skip its own deadline check.
        pass_at = clock()
        try:
            current = read_snapshot(
                projects,
                call=call,
                now=pass_at,
                self_session_id=resolved_session,
            )
        except FleetReadError as failure:
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_READ_FAILURES:
                _write(
                    stream,
                    fatal_line(
                        failure.function_id,
                        failure.detail,
                        MAX_CONSECUTIVE_READ_FAILURES,
                    ),
                )
                return READ_FAILURE_EXIT
            _write(
                stream,
                error_line(
                    failure.function_id,
                    failure.detail,
                    consecutive_failures,
                    MAX_CONSECUTIVE_READ_FAILURES,
                ),
            )
        else:
            consecutive_failures = 0
            for line in compare(previous, current, state):
                _write(stream, line)
            previous = current

        if duration > 0 and (pass_at - started).total_seconds() >= duration:
            return 0
        sleep(interval)


def _write(stream: TextIO, line: str) -> None:
    stream.write(f"{line}\n")
    stream.flush()


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fleet_delta_probe",
        description=(
            "Poll fleet state through registered reads and print one line "
            "per detected change."
        ),
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    parser.add_argument(
        "--project",
        dest="projects",
        action="append",
        default=None,
        help="Project slug or id to watch. Repeatable. Defaults to the "
        "checkout's mapped project.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"Seconds between passes (default {DEFAULT_INTERVAL_SECONDS}).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=DEFAULT_DURATION_SECONDS,
        help="Seconds to keep polling before exiting cleanly "
        f"(default {DEFAULT_DURATION_SECONDS}; 0 runs until interrupted).",
    )
    return parser.parse_args(list(argv))


def resolve_projects(requested: Sequence[str] | None) -> list[str]:
    """Return the projects to watch, defaulting to the checkout's own."""
    if requested:
        return list(requested)
    from yoke_core.domain.project_scratch_dir import resolve_active_project

    return [resolve_active_project()]


def main(argv: Sequence[str] | None = None) -> int:
    ns = _parse_args(list(sys.argv[1:] if argv is None else argv))
    if ns.interval <= 0:
        sys.stderr.write("fleet_delta_probe: --interval must be positive\n")
        return 2
    return run(
        resolve_projects(ns.projects),
        interval=ns.interval,
        duration=ns.duration,
    )


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    raise SystemExit(main())
