"""Poll fleet state and classify each observed change.

The wrapper routes this module's urgent tier to wakes while retaining every
line raw. Ambient identity survives handoff; bounded runs leave a sentinel.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence, TextIO

from yoke_contracts.project_contract.project_keys import (
    DEFAULT_STEERING_REPORT_INTERVAL_MINUTES,
    PROJECT_POLICY_CAPABILITY,
)

from yoke_core.domain.fleet_delta_alarms import DeltaState
from yoke_core.domain.fleet_delta_lines import compare, error_line, fatal_line
from yoke_core.domain.fleet_delta_snapshot import (
    FleetReadError,
    FleetSnapshot,
    read_snapshot,
)

DEFAULT_INTERVAL_SECONDS = 60
DEFAULT_DURATION_SECONDS = 3600
PROJECT_POLICY_FUNCTION = "projects.capability_settings.get"
STEERING_REPORT_FUNCTION = "steering.report.get"
STEERING_REPORT_INTERVAL_KEY = "steering_report_interval_minutes"
#: Consecutive failed passes before the probe stops instead of looping
#: silently against a control plane it cannot reach.
MAX_CONSECUTIVE_READ_FAILURES = 3
READ_FAILURE_EXIT = 1
WAKE_NOW = "urgent"
DEFER_TO_REPORT = "routine"
DELTA_WAKE_RULES = (
    (
        WAKE_NOW,
        re.compile(
            r"^fleet (?:(?:ERROR|FATAL)\b|inbox\b|ALARM "
            r"(?:idle-holder|unowned-item|starved-envelope)\b|"
            r"session \S+ terminated\b|item \S+ status .* -> (?:blocked|stopped)\b)"
        ),
    ),
    (
        DEFER_TO_REPORT,
        re.compile(
            r"^fleet (?:item \S+ (?:entered|status|claim|left-frontier)\b|"
            r"session \S+ (?:registered|ended)\b|"
            r"CLEAR (?:idle-holder|unowned-item|starved-envelope)\b)"
        ),
    ),
)

HELP_EPILOG = """\
Each pass reads the session roster, charge schedule, and durable inbox. Every
change stays in the raw capture. Failures, messages, alarms, abnormal ends,
and blocked items wake now; routine lifecycle and claim churn wait for the
next changed steering report. Identifiers are always printed whole.

Raw line shapes:
  fleet item YOK-N status <old> -> <new>
  fleet session <session-id> registered|ended|terminated surface=<surface>
  fleet inbox <message-id> state=pending|injected from=<session-id>
  fleet ALARM idle-holder|unowned-item|starved-envelope ...
  fleet CLEAR <alarm-kind> <subject>
"""


def delta_wake_tier(line: str) -> str | None:
    """Return this line's tier, refusing an unclassified fleet delta."""
    for tier, pattern in DELTA_WAKE_RULES:
        if pattern.search(line):
            return tier
    if line.startswith("fleet "):
        raise ValueError(
            "unclassified fleet delta; add its kind and tier to "
            f"DELTA_WAKE_RULES: {line.rstrip()}"
        )
    return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def dispatch_call(function_id: str, payload: dict[str, Any]) -> Any:
    """Call one registered read over the session's active transport."""
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        build_actor,
        call_dispatcher,
    )

    project = str(payload.get("project") or "").strip() or None
    return call_dispatcher(
        function_id=function_id,
        target=TargetRef(kind="global", project_id=project),
        payload=payload,
        actor=build_actor(),
    )


def ambient_session_id() -> str:
    """Resolve the calling session id from ambient harness identity."""
    from yoke_core.api.service_client_structured_api_adapter import build_actor

    return build_actor().session_id or ""


def _response_result(response: Any, function_id: str) -> dict[str, Any]:
    """Unwrap a registered read or raise a named fleet-read failure."""
    if not getattr(response, "success", False):
        error = getattr(response, "error", None)
        detail = (
            f"{error.code}: {error.message}" if error is not None else "unknown error"
        )
        raise FleetReadError(function_id, detail)
    return dict(getattr(response, "result", None) or {})


def _report_interval_minutes(
    project: str,
    *,
    call: Callable[[str, dict[str, Any]], Any],
) -> int:
    result = _response_result(
        call(
            PROJECT_POLICY_FUNCTION,
            {"project": project, "cap_type": PROJECT_POLICY_CAPABILITY},
        ),
        PROJECT_POLICY_FUNCTION,
    )
    try:
        settings = json.loads(str(result.get("settings_json") or "{}"))
    except (TypeError, ValueError) as exc:
        raise FleetReadError(
            PROJECT_POLICY_FUNCTION,
            f"project {project} returned invalid project-policy JSON",
        ) from exc
    if not isinstance(settings, Mapping):
        raise FleetReadError(
            PROJECT_POLICY_FUNCTION,
            f"project {project} project-policy must be a JSON object",
        )
    try:
        minutes = int(
            settings.get(
                STEERING_REPORT_INTERVAL_KEY,
                DEFAULT_STEERING_REPORT_INTERVAL_MINUTES,
            )
        )
    except (TypeError, ValueError):
        minutes = DEFAULT_STEERING_REPORT_INTERVAL_MINUTES
    return max(1, minutes)


def _append_steering_reports(
    projects: Sequence[str],
    *,
    observed_at: datetime,
    stream: TextIO,
    call: Callable[[str, dict[str, Any]], Any],
    last_checks: dict[str, datetime],
    last_fingerprints: dict[str, str],
) -> None:
    """Append changed reports after a real delta batch, subject to policy."""
    for project in projects:
        try:
            interval = _report_interval_minutes(project, call=call)
            last_check = last_checks.get(project)
            if last_check is not None and observed_at - last_check < timedelta(
                minutes=interval
            ):
                continue
            result = _response_result(
                call(STEERING_REPORT_FUNCTION, {"project": project}),
                STEERING_REPORT_FUNCTION,
            )
            fingerprint = str(result.get("fingerprint") or "").strip()
            body = str(result.get("body") or "").strip()
            if not fingerprint or not body:
                raise FleetReadError(
                    STEERING_REPORT_FUNCTION,
                    f"project {project} response omitted fingerprint or body",
                )
            last_checks[project] = observed_at
            if last_fingerprints.get(project) == fingerprint:
                continue
            last_fingerprints[project] = fingerprint
            _write(stream, body)
        except FleetReadError as failure:
            _write(
                stream,
                f"fleet ERROR steering report unavailable project={project} "
                f"via {failure.function_id}: {failure.detail}; check "
                f"`yoke steering report get --project {project}`, then keep "
                "the fleet watch armed for the next real delta",
            )


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
    """Poll until *duration* elapses, printing changes and steering context.

    ``call``, ``clock``, and ``sleep`` are seams so the loop is testable
    without a control plane and without wall-clock waiting.
    """
    stream = out if out is not None else sys.stdout
    resolved_session = session_id if session_id is not None else ambient_session_id()
    state = DeltaState()
    previous: FleetSnapshot | None = None
    consecutive_failures = 0
    last_report_checks: dict[str, datetime] = {}
    last_report_fingerprints: dict[str, str] = {}
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
            delta_lines = compare(previous, current, state)
            for line in delta_lines:
                delta_wake_tier(line)
                _write(stream, line)
            if delta_lines:
                _append_steering_reports(
                    projects,
                    observed_at=pass_at,
                    stream=stream,
                    call=call,
                    last_checks=last_report_checks,
                    last_fingerprints=last_report_fingerprints,
                )
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
