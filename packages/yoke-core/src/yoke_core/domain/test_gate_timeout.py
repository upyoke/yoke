"""Keep test execution budgets separate from gate-admission waits."""

from __future__ import annotations

import os
import shlex
from collections.abc import MutableMapping


WATCH_PYTEST_MODULE = "yoke_core.tools.watch_pytest"
WATCH_EXECUTION_TIMEOUT_ENV = "YOKE_WATCH_EXECUTION_TIMEOUT_SECONDS"


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
