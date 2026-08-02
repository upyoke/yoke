"""Boundary cases for resuming onboarding into another folder."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.cli.test_yoke_operations_cli_onboard_resume_cli import _preview
from yoke_cli.commands.adapters import onboard as onboard_adapter
from yoke_cli.config import onboard_apply_report


def test_use_different_folder_refuses_existing_local_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    checkout = tmp_path / "existing"
    checkout.mkdir()
    writer = onboard_apply_report.ApplyReportWriter.start(
        _preview(),
        {"project_mode": "local-checkout", "project_checkout": str(checkout)},
    )
    run_id = writer.summary()["run_id"]
    rc = onboard_adapter.onboard(["--use-different-folder", run_id, "--yes"])
    assert rc == 2
    assert "no run-created checkout Yoke can preserve" in capsys.readouterr().err
    assert checkout.is_dir()
