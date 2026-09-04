"""The remote branch of ``watch_pytest``: the CI selection under the watcher.

Runs :mod:`yoke_core.tools.pytest_remote_selection_run` as the watched
child and classifies what it says. ``Workflow status:`` polls are progress
and ride the digest; the engine's own narration (which run, how it came to
be, what it concluded) is summary and lands at once; errors and the
pytest ``FAILED`` lines relayed from the failed step's log are urgent.
"""

from __future__ import annotations

import re
import shlex
import time
from pathlib import Path

from yoke_core.tools import _watch_pytest_wall_clock, _watch_runner
from yoke_core.tools._watch_pytest_classify import classify_pytest_line
from yoke_core.tools._watch_throttle import Classification, LineClass
from yoke_core.tools.pytest_remote_selection import LOCAL_FLAG, PREFIX, RemoteRoute

_WORKFLOW_STATUS_RE = re.compile(r"Workflow status: .*\(elapsed: (\d+)s")
_URGENT_PREFIXES = ("Error:",)
_SUMMARY_PREFIXES = (PREFIX, "Workflow dispatch intent is pending recovery")
_NOISE_PREFIXES = ("GitHub Actions status via",)


def classify_remote_line(line: str) -> Classification:
    """Classify one line of the remote selection engine's output."""
    text = line.strip()
    if text.startswith(_URGENT_PREFIXES):
        return Classification(LineClass.URGENT)
    if text.startswith(_SUMMARY_PREFIXES):
        return Classification(LineClass.SUMMARY)
    poll = _WORKFLOW_STATUS_RE.search(text)
    if poll:
        return Classification(LineClass.PROGRESS, progress_value=float(poll.group(1)))
    if text.startswith(_NOISE_PREFIXES):
        return Classification(LineClass.NOISE)
    return classify_pytest_line(line)


def header(route: RemoteRoute, kind: str) -> str:
    """The start-of-stream line naming where and what this run tests."""
    dropped = (
        f"; dropped machine-local args {shlex.join(route.dropped_args)}"
        if route.dropped_args
        else ""
    )
    base = route.base_sha[:12] if route.base_sha else "explicit paths"
    return (
        f"# watch_{kind} remote-selection: {route.workflow} on "
        f"{route.repo}@{route.branch} head={route.head_sha[:12]} base={base}"
        f"{dropped}; pass {LOCAL_FLAG} to run on this machine"
    )


def run(
    route: RemoteRoute,
    *,
    kind: str,
    raw_capture: Path,
    progress_capture: Path,
    flush_seconds: float,
    timeout_seconds: float | None,
) -> int:
    """Drive the remote engine under the watcher; return its exit status."""
    started = time.monotonic()
    exit_code = _watch_runner.run_watcher(
        argv=route.engine_argv(),
        classifier=classify_remote_line,
        raw_capture=raw_capture,
        progress_capture=progress_capture,
        kind=kind,
        cwd=str(route.root),
        flush_seconds=flush_seconds,
        timeout_seconds=timeout_seconds,
        header_metadata=header(route, kind),
    )
    _watch_pytest_wall_clock.report(time.monotonic() - started, raw_capture)
    return exit_code


__all__ = ["classify_remote_line", "header", "run"]
