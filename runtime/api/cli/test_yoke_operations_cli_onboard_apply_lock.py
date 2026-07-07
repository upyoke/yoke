from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli.commands.adapters import onboard as onboard_adapter
from yoke_cli.config import onboard_apply_lock


def test_active_apply_lock_blocks_second_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    config = tmp_path / "home" / "config.json"

    with onboard_apply_lock.acquire("run-held"):
        rc = onboard_adapter.onboard([
            "--config", str(config),
            "--env", "stage",
            "--api-url", "https://api.stage.example",
            "--yes",
            "--non-interactive",
            "--skip-identity-check",
            "yoke-token",
        ])

    assert rc == 1
    err = capsys.readouterr().err
    assert "another onboarding apply is already running" in err


def test_stale_apply_lock_is_replaced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    path = onboard_apply_lock.lock_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"pid": -1}) + "\n", encoding="utf-8")

    with onboard_apply_lock.acquire("run-new"):
        assert path.is_file()

    assert not path.exists()
