"""Clean-wheel proof for Browser QA setup/status commands."""

from __future__ import annotations

import json
from pathlib import Path

from runtime.api.cli.yoke_product_distribution_wheel_test_support import (
    _assert_command,
    _product_env,
)


def test_product_wheel_runs_browser_qa_setup_and_status(
    tmp_path: Path,
    product_wheelhouse: Path,
    product_venv: Path,
) -> None:
    venv_dir = product_venv
    yoke = venv_dir / "bin" / "yoke"

    project = tmp_path / "external-project"
    machine_home = tmp_path / "home" / ".yoke"
    project.mkdir()
    machine_home.mkdir(parents=True)
    env = _product_env(machine_home=machine_home, venv_dir=venv_dir)

    status = _assert_command(
        yoke,
        project,
        env,
        ["qa", "browser", "status", "--project", "fixture", "--json"],
        0,
    )
    status_payload = json.loads(status.stdout)
    assert status_payload["daemon"]["status"] == "not_running"

    setup = _assert_command(
        yoke,
        project,
        env,
        ["qa", "browser", "setup", "--project", "fixture", "--dry-run", "--json"],
        0,
    )
    setup_payload = json.loads(setup.stdout)
    assert setup_payload["ok"] is True
    assert setup_payload["dry_run"] is True
    assert setup_payload["readiness"]["daemon"]["status"] == "not_running"
    assert setup_payload["runtime_dir"].endswith("/.yoke/browser-runtime")
    runtime_dir = Path(setup_payload["runtime_dir"])
    assert (runtime_dir / "src" / "aria_snapshot_parser.js").is_file()
    assert (runtime_dir / "tests" / "snapshot.test.js").is_file()
