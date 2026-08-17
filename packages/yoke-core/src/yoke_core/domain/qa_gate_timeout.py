"""Keep QA execution budgets separate from gate-admission waits."""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import MutableMapping

from yoke_core.domain.qa_constants import MAX_CASE_COMMAND_TIMEOUT_SECONDS


WATCH_PYTEST_MODULE = "yoke_core.tools.watch_pytest"
WATCH_EXECUTION_TIMEOUT_ENV = "YOKE_WATCH_EXECUTION_TIMEOUT_SECONDS"

#: Announced by admission control the moment a queued gate is let through.
#: The emitter and every reader of a captured run share this one phrasing so
#: a recorded run can attribute its elapsed time to the queue rather than to
#: the suite.
SLOT_ACQUIRED_PREFIX = "gate admission: slot acquired after "

_SLOT_ACQUIRED_RE = re.compile(re.escape(SLOT_ACQUIRED_PREFIX) + r"(\d+(?:\.\d+)?)s")

#: Upper bound on how long a gate may queue for an admission slot.
#: The execution budget above starts only once a gate is admitted, and the
#: parent-process timeout is handed off rather than kept, so queue time sits
#: between two clocks that neither of them measures. This is the bound on
#: that gap: generous enough that a real queue behind a full suite still
#: drains, short enough that a wait nobody will ever satisfy ends as a
#: diagnosable event instead of a process that never returns.
WAIT_TIMEOUT_ENV = "YOKE_TEST_GATE_WAIT_TIMEOUT_SECONDS"
DEFAULT_WAIT_TIMEOUT_S = 3600.0


def wait_timeout_seconds(env: MutableMapping[str, str] | None = None) -> float:
    """Read the admission-queue bound, falling back to the default.

    Raises ``ValueError`` rather than accepting a non-positive override:
    "wait forever" is the failure mode the bound exists to remove, so it is
    not reachable by setting the knob to zero.
    """
    value = (env or os.environ).get(WAIT_TIMEOUT_ENV)
    if value is None:
        return DEFAULT_WAIT_TIMEOUT_S
    try:
        timeout_seconds = float(value)
    except ValueError as exc:
        raise ValueError(f"{WAIT_TIMEOUT_ENV} must be a positive number") from exc
    if timeout_seconds <= 0:
        raise ValueError(f"{WAIT_TIMEOUT_ENV} must be a positive number")
    return timeout_seconds


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


def timeout_summary(
    timeout_seconds: int,
    slot_wait_seconds: float | None,
    *,
    elapsed_compute_seconds: float | None = None,
    requirement_id: int | None = None,
) -> str:
    """State plainly that a run hit its budget rather than failing tests.

    A timed-out run records the same ``fail`` verdict a broken branch does,
    and a queued gate's capture ends mid-suite with no failures in it. This
    sentence is what separates the two for whoever reads the record.
    """
    compute = (
        float(timeout_seconds)
        if elapsed_compute_seconds is None
        else max(0.0, elapsed_compute_seconds)
    )
    summary = (
        f"execution budget {timeout_seconds}s was exhausted after "
        f"{compute:.0f}s of compute"
    )
    if slot_wait_seconds is not None:
        summary += (
            f", having first waited {slot_wait_seconds:.0f}s for a machine-wide "
            "test-gate slot that is not charged to the budget"
        )
    retry_budget = min(
        timeout_seconds * 2,
        MAX_CASE_COMMAND_TIMEOUT_SECONDS,
    )
    retry = "yoke qa case run"
    if requirement_id is not None:
        retry += f" --requirement-id {requirement_id}"
    retry += f" --timeout-seconds {retry_budget}"
    return (
        summary
        + "; the run was reaped at the deadline, not failing tests; "
        + f"retry with `{retry}`"
    )
