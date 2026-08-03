"""Line classifier for pytest output.

Sibling of :mod:`yoke_core.tools.watch_pytest`, which re-exports every
name here so callers keep one import site. Split out to keep the wrapper
under the authored-file line cap, alongside the existing
``_watch_pytest_args`` / ``_watch_pytest_rootdir`` /
``_watch_pytest_wall_clock`` siblings.
"""

from __future__ import annotations

import re

from yoke_core.tools._watch_throttle import Classification, LineClass


# Per-class regexes. Each is line-oriented; callers feed one line at a
# time. Keeping them as separate constants lets tests exercise each
# class independently without re-parsing the union pattern.
PYTEST_PROGRESS_RE = re.compile(r"\[\s*(\d+)%\]")
# Per-test summary lines (``FAILED path::test``, ``ERROR path``) plus the
# collection/usage error shapes a watcher must relay so callers do not
# need the raw capture to diagnose a bad invocation: ``ERROR: file or
# directory not found:`` / ``ERROR: usage:`` (UsageError lead lines),
# ``<prog>: error: …`` (argparse detail — the prog token may contain
# spaces, e.g. ``python3 -m pytest: error: …``), xdist ``INTERNALERROR>``
# crash frames, and the non-top-level conftest ``pytest_plugins`` error
# (which xdist surfaces inside ERRORS-section blocks without a prefix).
PYTEST_URGENT_RE = re.compile(
    r"^(?:FAILED|ERROR)[ :]"
    r"|^INTERNALERROR"
    r"|^\S.*?: error: "
    r"|Defining 'pytest_plugins' in a non-top-level conftest"
)
# Closing summary banner. Matches pytest's default-verbose banner
# (``====== 4 passed in 0.42s ======``, ``==== ERRORS ====``,
# ``==== no tests ran in 0.01s ====``) AND pytest's ``-q`` quiet-mode
# verdict lines (``4 passed in 0.42s``, ``no tests ran in 0.01s`` — no
# leading ``=``). The count-led quiet shape requires count + verdict
# word + (`,` or ` in `) so noise lines starting with a digit do not
# accidentally match.
PYTEST_SUMMARY_BANNER_RE = re.compile(
    r"^=+ .*(passed|failed|error|ERRORS|no tests ran)"
    r"|"
    r"^\d+ (passed|failed|error|skipped|xfailed|xpassed|deselected)(,| in )"
    r"|"
    r"^no tests ran in "
)
# Initial collection notice: plain ``collected N items`` plus the xdist
# form ``N workers [M items]`` (the only collection signal xdist prints).
PYTEST_COLLECTED_RE = re.compile(
    r"^collected (?P<plain>\d+)|^\d+ workers \[(?P<xdist>\d+) items?\]"
)

# Public union pattern: kept for callers/tests that want a single
# "is this a signal line?" check. Composed from the per-class regexes
# above so there is exactly one source of truth for each shape.
PYTEST_PROGRESS_PATTERN = re.compile(
    r"|".join(
        (
            PYTEST_PROGRESS_RE.pattern,
            PYTEST_URGENT_RE.pattern,
            PYTEST_SUMMARY_BANNER_RE.pattern,
            PYTEST_COLLECTED_RE.pattern,
        )
    )
)


def classify_pytest_line(line: str) -> Classification:
    """Classify a single non-TTY pytest output line.

    Order matters: failure summaries that *also* contain a percent token
    in their narrative (rare, but possible inside test names) must still
    classify as ``URGENT`` so they emit immediately. We check
    URGENT and SUMMARY before PROGRESS for that reason.
    """
    if PYTEST_URGENT_RE.search(line):
        return Classification(LineClass.URGENT)
    if PYTEST_SUMMARY_BANNER_RE.search(line):
        return Classification(LineClass.SUMMARY)
    if PYTEST_COLLECTED_RE.search(line):
        return Classification(LineClass.SUMMARY)
    match = PYTEST_PROGRESS_RE.search(line)
    if match:
        return Classification(LineClass.PROGRESS, progress_value=float(match.group(1)))
    return Classification(LineClass.NOISE)


def pytest_collected_item_count(line: str) -> int | None:
    """Return the collected item count carried by a pytest notice."""
    match = PYTEST_COLLECTED_RE.search(line)
    if match is None:
        return None
    return int(match.group("plain") or match.group("xdist"))


__all__ = [
    "PYTEST_COLLECTED_RE",
    "PYTEST_PROGRESS_PATTERN",
    "PYTEST_PROGRESS_RE",
    "PYTEST_SUMMARY_BANNER_RE",
    "PYTEST_URGENT_RE",
    "classify_pytest_line",
    "pytest_collected_item_count",
]
