"""Locate the part of one failed GitHub Actions job log that explains it.

The end of a job log is teardown — artifact uploads, cache saves, job
cleanup — so a plain tail shows everything except the failure. This
module finds the failure region instead:

1. pytest's ``FAILURES`` / ``ERRORS`` section through the end of its
   step, which carries every assertion and the short test summary;
2. otherwise the step holding the first ``##[error]`` annotation, which
   ends at the error that failed it;
3. otherwise the log itself, with post-job teardown removed.

The region is bounded by lines and bytes. A pytest region keeps its head
(the first failure's traceback) and its tail (the short test summary);
the other regions keep their tail, where a step's failure lands. Trimmed
lines are named in the region, never dropped silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Sequence, Tuple


# Default lines shown per failed job when the caller names no bound.
DEFAULT_REGION_LINES = 200
# A single line longer than this is cut, so one minified blob cannot
# spend a job's whole byte share.
MAX_LINE_CHARS = 2_000

REGION_PYTEST = "pytest_failures"
REGION_ERROR_STEP = "failing_step"
REGION_LOG = "log_end"

_TIMESTAMP = re.compile(r"^﻿?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ?")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_PYTEST_SECTION = re.compile(r"^=+ (?:FAILURES|ERRORS) =+$")
_STEP_START = "##[group]Run "
_ERROR_ANNOTATION = "##[error]"
_POST_JOB_MARKERS = ("##[group]Post ", "Post job cleanup.")


@dataclass(frozen=True)
class FailureRegion:
    """The bounded failure region of one job log."""

    kind: str
    lines: List[str]
    log_line_count: int
    region_line_count: int
    trimmed_line_count: int


def failure_region(text: str, *, max_lines: int, max_bytes: int) -> FailureRegion:
    """Return the bounded failure region of one job's log *text*."""
    lines = _clean_lines(text)
    kind, start, end = _locate(lines)
    region = lines[start:end]
    shown, trimmed = _bound(
        region,
        max_lines=max_lines,
        max_bytes=max_bytes,
        keep_head=kind == REGION_PYTEST,
    )
    return FailureRegion(
        kind=kind,
        lines=shown,
        log_line_count=len(lines),
        region_line_count=len(region),
        trimmed_line_count=trimmed,
    )


def _clean_lines(text: str) -> List[str]:
    cleaned: List[str] = []
    for raw in text.splitlines():
        line = _ANSI.sub("", _TIMESTAMP.sub("", raw, count=1)).rstrip()
        if any(marker in line for marker in _POST_JOB_MARKERS):
            break
        if len(line) > MAX_LINE_CHARS:
            cut = len(line) - MAX_LINE_CHARS
            line = f"{line[:MAX_LINE_CHARS]} ... [{cut} characters cut]"
        cleaned.append(line)
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()
    return cleaned


def _locate(lines: Sequence[str]) -> Tuple[str, int, int]:
    for index, line in enumerate(lines):
        if _PYTEST_SECTION.match(line.strip()):
            return REGION_PYTEST, index, _step_end(lines, index)
    for index, line in enumerate(lines):
        if line.startswith(_ERROR_ANNOTATION):
            return REGION_ERROR_STEP, _step_start(lines, index), _step_end(lines, index)
    return REGION_LOG, 0, len(lines)


def _step_start(lines: Sequence[str], index: int) -> int:
    for position in range(index, -1, -1):
        if lines[position].startswith(_STEP_START):
            return position
    return 0


def _step_end(lines: Sequence[str], index: int) -> int:
    for position in range(index + 1, len(lines)):
        if lines[position].startswith(_STEP_START):
            return position
    return len(lines)


def _bound(
    region: List[str],
    *,
    max_lines: int,
    max_bytes: int,
    keep_head: bool,
) -> Tuple[List[str], int]:
    if len(region) <= max_lines and _size(region) <= max_bytes:
        return list(region), 0
    head_lines = max_lines // 2 if keep_head else 0
    head = _take(region, head_lines, max_bytes // 2 if keep_head else 0)
    rest = region[len(head) :]
    tail = _take(rest[::-1], max_lines - len(head), max_bytes - _size(head))[::-1]
    trimmed = len(region) - len(head) - len(tail)
    marker = (
        f"... {trimmed} line(s) of this job's failure region trimmed to fit "
        "the report; --full writes the complete log to a local file"
    )
    return [*head, marker, *tail], trimmed


def _take(lines: Sequence[str], max_lines: int, max_bytes: int) -> List[str]:
    taken: List[str] = []
    used = 0
    for line in lines[: max(max_lines, 0)]:
        cost = len(line.encode("utf-8")) + 1
        if used + cost > max_bytes:
            break
        taken.append(line)
        used += cost
    return taken


def _size(lines: Sequence[str]) -> int:
    return sum(len(line.encode("utf-8")) + 1 for line in lines)


__all__ = [
    "DEFAULT_REGION_LINES",
    "FailureRegion",
    "REGION_ERROR_STEP",
    "REGION_LOG",
    "REGION_PYTEST",
    "failure_region",
]
