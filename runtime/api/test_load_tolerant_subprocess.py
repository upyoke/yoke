"""Tests for the shared load-tolerant subprocess budget."""

from __future__ import annotations

import subprocess
from unittest import SkipTest

import pytest

from runtime.api import load_tolerant_subprocess as budget


def test_runner_owns_the_shared_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}
    completed = subprocess.CompletedProcess(["probe"], 0, "ok", "")

    def run(command, **kwargs):
        observed["command"] = command
        observed.update(kwargs)
        return completed

    monkeypatch.setattr(budget.subprocess, "run", run)

    result = budget.run_load_tolerant_subprocess(
        ["probe"], purpose="checking the product boundary", text=True,
    )

    assert result is completed
    assert observed["command"] == ["probe"]
    assert observed["timeout"] == budget.LOAD_TOLERANT_SUBPROCESS_TIMEOUT_SECONDS


def test_budget_exhaustion_is_a_distinct_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def time_out(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(budget.subprocess, "run", time_out)

    with pytest.raises(SkipTest, match="host load.*not reported as a product"):
        budget.run_load_tolerant_subprocess(
            ["slow-probe"], purpose="checking the product boundary",
        )


def test_callers_cannot_replace_the_shared_timeout() -> None:
    with pytest.raises(TypeError, match="shared load-tolerant budget"):
        budget.run_load_tolerant_subprocess(
            ["probe"], purpose="checking the product boundary", timeout=1,
        )
