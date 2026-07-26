"""``yoke onboard checklist init`` adapter shapes: installer and standalone."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.cli.onboard_checklist_cli_test_helpers import (
    init_result,
    run_cli,
)


def test_init_installer_shape_dispatches_and_json_is_response_driven(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    machine_config = tmp_path / "home" / "config.json"
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    result = init_result(
        machine_config_path=str(machine_config),
        checkout_path=str(checkout),
    )

    rc, calls = run_cli(
        [
            "onboard",
            "checklist",
            "init",
            "--config",
            str(machine_config),
            "--checkout",
            str(checkout),
            "--project-id",
            "7",
            "--json",
        ],
        result=result,
    )

    assert rc == 0
    call = calls[-1]
    assert call["function_id"] == "onboard.checklist.init"
    assert call["target"].kind == "global"
    assert call["target"].project_id == "7"
    assert call["payload"] == {
        "machine_config_path": str(machine_config),
        "checkout_path": str(checkout),
        "project_id": 7,
    }
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["success"] is True
    assert envelope["function"] == "onboard.checklist.init"
    assert envelope["result"]["operation"] == "onboard.checklist.init"
    assert envelope["result"]["machine_config_path"] == str(machine_config)


def test_init_standalone_project_ref_replaces_config(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    result = init_result(machine_config_path=None, checkout_path=str(checkout))

    rc, calls = run_cli(
        [
            "onboard",
            "checklist",
            "init",
            "--project",
            "demo",
            "--checkout",
            str(checkout),
            "--json",
        ],
        result=result,
    )

    assert rc == 0
    call = calls[-1]
    assert call["function_id"] == "onboard.checklist.init"
    assert call["target"].kind == "global"
    assert call["target"].project_id == "demo"
    assert call["payload"] == {
        "machine_config_path": None,
        "checkout_path": str(checkout),
        "project_id": None,
        "project": "demo",
    }
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["success"] is True


def test_init_without_config_requires_project_and_checkout(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()

    rc_no_project, calls_no_project = run_cli(
        ["onboard", "checklist", "init", "--checkout", str(checkout)],
        result=init_result(),
    )
    assert rc_no_project == 1
    assert "requires both" in capsys.readouterr().err
    assert calls_no_project == []

    rc_no_checkout, calls_no_checkout = run_cli(
        ["onboard", "checklist", "init", "--project", "demo"],
        result=init_result(),
    )
    assert rc_no_checkout == 1
    assert "requires both" in capsys.readouterr().err
    assert calls_no_checkout == []
