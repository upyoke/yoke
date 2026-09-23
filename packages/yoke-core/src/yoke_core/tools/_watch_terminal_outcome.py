"""Resolve and render the terminal result of an outcome-only watch."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import TextIO

_JSON_ERROR_FIELD_RE = re.compile(r'^\s*"error"\s*:\s*(.+)\s*$')
_TERMINAL_LINE_RE = re.compile(
    r"^\s*(?:(?:\[tests\]\s*)?(?:Error:|ERROR:|fatal:|"
    r"Step runner diagnostic:|Merge halted:|Merge lock error:|HARD STOP:|"
    r"FAIL(?:ED)?\b|deploy driver source drift:)|.*(?:could not (?:copy|read)\b|"
    r"receipt was not recorded\b|release gate will still refuse\b))",
    re.IGNORECASE,
)
PYTHON_EXCEPTION_PATTERN = re.compile(
    r"^\s*(?:[A-Za-z_][\w.]*?(?:Error|Exception)|SystemExit|KeyboardInterrupt):"
)
OUTCOME_ONLY_WATCH_KINDS = frozenset({"merge", "deploy"})
_WATCH_FAILURE_RE = re.compile(
    r"^\s*# watch_\w+ (?:launch_error|timed out|aborted|interrupted by signal)\b",
    re.IGNORECASE,
)
_TRANSIENT_RE = re.compile(r"temporarily unavailable.*retrying", re.IGNORECASE)


def _compact(line: str) -> str:
    return " ".join(line.split())


def terminal_error_from_raw_capture(raw_capture: Path) -> str | None:
    """Return the last string-valued JSON error field in a raw capture."""
    latest = ""
    with raw_capture.open(encoding="utf-8", errors="replace") as capture:
        for line in capture:
            match = _JSON_ERROR_FIELD_RE.match(line)
            if match is None:
                continue
            encoded = match.group(1).rstrip().removesuffix(",")
            try:
                value = json.loads(encoded)
            except (TypeError, ValueError):
                continue
            if isinstance(value, str) and value.strip():
                latest = _compact(value)
    return latest or None


def _terminal_cause(raw_capture: Path) -> str | None:
    latest = terminal_error_from_raw_capture(raw_capture)
    with raw_capture.open(encoding="utf-8", errors="replace") as capture:
        for line in capture:
            if _TRANSIENT_RE.search(line):
                continue
            if (
                _TERMINAL_LINE_RE.match(line)
                or PYTHON_EXCEPTION_PATTERN.match(line)
                or _WATCH_FAILURE_RE.match(line)
            ):
                latest = _compact(line)
    return latest


def format_terminal_outcome(
    *,
    kind: str,
    exit_code: int,
    raw_capture: Path,
    result_summary: str | None = None,
) -> str:
    """Render one final result after the watched child has exited."""
    if exit_code == 0:
        result = _compact(result_summary) if result_summary else ""
        detail = f"; result: {result}" if result else ""
        return (
            f"# watch_{kind} outcome: completed successfully{detail}; "
            f"exit=0; raw={raw_capture}\n"
        )

    cause = _terminal_cause(raw_capture)
    if cause is None:
        cause = "terminal cause not diagnosed from captured output"
        recovery = "inspect the raw capture before retrying"
    elif "nested_admission_deadlock" in cause:
        recovery = (
            "retry after the enclosing admission slot releases; avoid nested "
            "work that reacquires that slot"
        )
    elif "timed out" in cause.lower():
        recovery = (
            "inspect the last captured output; raise the timeout only if the "
            "expected work needs longer"
        )
    elif "launch_error" in cause:
        recovery = "verify the command or module is available in this environment"
    else:
        recovery = "follow the repair in the error and inspect the capture for context"
    return (
        f"# watch_{kind} failure: {cause}; exit={exit_code}; "
        f"recovery: {recovery}; raw={raw_capture}\n"
    )


def is_python_exception_line(line: str) -> bool:
    """Whether *line* names a terminal Python exception."""
    return PYTHON_EXCEPTION_PATTERN.match(line) is not None


def emit_terminal_outcome(
    *,
    kind: str,
    exit_code: int,
    raw_capture: Path,
    raw_f: TextIO,
    progress_f: TextIO,
    out: TextIO,
    result_summary: str | None = None,
) -> None:
    """Write the final result and required exit sentinel to both streams."""
    raw_f.flush()
    outcome = format_terminal_outcome(
        kind=kind,
        exit_code=exit_code,
        raw_capture=raw_capture,
        result_summary=result_summary,
    )
    for line in (outcome, f"# watch_{kind} exit={exit_code} raw={raw_capture}\n"):
        progress_f.write(line)
        progress_f.flush()
        out.write(line)
        out.flush()


def emit_terminal_failure(
    *,
    kind: str,
    message: str,
    exit_code: int,
    raw_capture: Path,
    progress_capture: Path,
    out: TextIO | None = None,
) -> int:
    """Record a wrapper preflight refusal in raw and the user-facing stream."""
    raw_capture.parent.mkdir(parents=True, exist_ok=True)
    progress_capture.parent.mkdir(parents=True, exist_ok=True)
    with raw_capture.open("a", encoding="utf-8", buffering=1) as raw_f:
        raw_f.write(f"Error: {message.rstrip()}\n")
    stream = sys.stderr if out is None else out
    with raw_capture.open("a", encoding="utf-8") as raw_f, progress_capture.open(
        "a", encoding="utf-8", buffering=1
    ) as progress_f:
        emit_terminal_outcome(
            kind=kind,
            exit_code=exit_code,
            raw_capture=raw_capture,
            raw_f=raw_f,
            progress_f=progress_f,
            out=stream,
        )
    return exit_code


__all__ = [
    "OUTCOME_ONLY_WATCH_KINDS",
    "PYTHON_EXCEPTION_PATTERN",
    "emit_terminal_outcome",
    "emit_terminal_failure",
    "format_terminal_outcome",
    "is_python_exception_line",
    "terminal_error_from_raw_capture",
]
