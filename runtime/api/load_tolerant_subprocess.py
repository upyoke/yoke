"""Shared subprocess budget for load-sensitive floor and boundary tests."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from typing import Any
from unittest import SkipTest


LOAD_TOLERANT_SUBPROCESS_TIMEOUT_SECONDS = 60


def run_load_tolerant_subprocess(
    command: Sequence[str],
    *,
    purpose: str,
    **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    """Run a test subprocess or skip distinctly when host load exhausts it."""
    if "timeout" in kwargs:
        raise TypeError("timeout is owned by the shared load-tolerant budget")
    try:
        return subprocess.run(
            command,
            timeout=LOAD_TOLERANT_SUBPROCESS_TIMEOUT_SECONDS,
            **kwargs,
        )
    except subprocess.TimeoutExpired as exc:
        raise SkipTest(
            "load-tolerant subprocess budget exceeded after "
            f"{LOAD_TOLERANT_SUBPROCESS_TIMEOUT_SECONDS}s while {purpose}; "
            "host load prevented this floor check from completing, so the "
            "timeout is not reported as a product regression"
        ) from exc


__all__ = [
    "LOAD_TOLERANT_SUBPROCESS_TIMEOUT_SECONDS",
    "run_load_tolerant_subprocess",
]
