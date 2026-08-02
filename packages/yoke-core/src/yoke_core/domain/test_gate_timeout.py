"""Keep test execution budgets separate from gate-admission waits."""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import MutableMapping


WATCH_PYTEST_MODULE = "yoke_core.tools.watch_pytest"
WATCH_EXECUTION_TIMEOUT_ENV = "YOKE_WATCH_EXECUTION_TIMEOUT_SECONDS"

#: Announced by admission control the moment a queued gate is let through.
#: The emitter and every reader of a captured run share this one phrasing so
#: a recorded run can attribute its elapsed time to the queue rather than to
#: the suite.
SLOT_ACQUIRED_PREFIX = "gate admission: slot acquired after "

_SLOT_ACQUIRED_RE = re.compile(re.escape(SLOT_ACQUIRED_PREFIX) + r"(\d+(?:\.\d+)?)s")


def process_timeout_for_command(
    command: str,
    timeout_seconds: int,
    env: MutableMapping[str, str],
) -> int | None:
    """Return the parent-process timeout for a registered command.

    ``watch_pytest`` waits for a shared gate before it launches pytest. Its
    execution budget therefore belongs inside the watcher, after admission,
    rather than on the parent process that includes queue time.
    """
    try:
        command_tokens = shlex.split(command)
    except ValueError:
        return timeout_seconds
    if WATCH_PYTEST_MODULE not in command_tokens:
        return timeout_seconds
    env[WATCH_EXECUTION_TIMEOUT_ENV] = str(timeout_seconds)
    return None


def execution_timeout_from_env(
    env: MutableMapping[str, str] | None = None,
) -> int | None:
    """Read the post-admission execution budget for a watched pytest run."""
    value = (env or os.environ).get(WATCH_EXECUTION_TIMEOUT_ENV)
    if value is None:
        return None
    try:
        timeout_seconds = int(value)
    except ValueError as exc:
        raise ValueError(
            f"{WATCH_EXECUTION_TIMEOUT_ENV} must be a positive integer"
        ) from exc
    if timeout_seconds < 1:
        raise ValueError(f"{WATCH_EXECUTION_TIMEOUT_ENV} must be a positive integer")
    return timeout_seconds


def announced_slot_wait_seconds(output: str) -> float | None:
    """Return the admission wait announced in *output*, or None.

    A gate that never queued announces nothing, so absence means the run
    started immediately rather than that the wait is unknown.
    """
    match = _SLOT_ACQUIRED_RE.search(output)
    return float(match.group(1)) if match is not None else None


def timeout_summary(timeout_seconds: int, slot_wait_seconds: float | None) -> str:
    """State plainly that a run hit its budget rather than failing tests.

    A timed-out run records the same ``fail`` verdict a broken branch does,
    and a queued gate's capture ends mid-suite with no failures in it. This
    sentence is what separates the two for whoever reads the record.
    """
    summary = f"timed out after {timeout_seconds}s of execution"
    if slot_wait_seconds is not None:
        summary += (
            f", having first waited {slot_wait_seconds:.0f}s for a machine-wide "
            "test-gate slot that is not charged to the budget"
        )
    return summary + "; the run was reaped at the deadline, not failing tests"
