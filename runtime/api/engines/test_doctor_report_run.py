"""Tests for shared Doctor subprocess execution helpers."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from yoke_core.engines import doctor_report


def test_run_timeout_returns_bounded_completed_process() -> None:
    def _timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["slow-command"], timeout=3, output="partial", stderr="hung",
        )

    with patch("yoke_core.engines.doctor_report.subprocess.run", _timeout):
        result = doctor_report._run(["slow-command"], timeout=3)

    assert result.returncode == 124
    assert result.stdout == "partial"
    assert "timeout after 3s" in result.stderr
    assert "hung" in result.stderr
