"""Clean-wheel proof for Browser QA setup/status commands."""

from __future__ import annotations

import json
from yoke_core.tools.build_release import create_seeded_pip_venv
from pathlib import Path

from runtime.api.cli.test_yoke_product_distribution_wheel import (
    _assert_command,
    _product_env,
    _run,
)


def test_product_wheel_runs_browser_qa_setup_and_status(
    tmp_path: Path,
    product_wheelhouse: Path,
) -> None:
    venv_dir = tmp_path / "venv"
    create_seeded_pip_venv(venv_dir)
    venv_python = venv_dir / "bin" / "python"
    yoke = venv_dir / "bin" / "yoke"
    _run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            str(product_wheelhouse),
            "yoke-cli",
            "yoke-harness",
        ],
        cwd=tmp_path,
        timeout=120,
    )

    project = tmp_path / "external-project"
    machine_home = tmp_path / "home" / ".yoke"
    project.mkdir()
    machine_home.mkdir(parents=True)
    env = _product_env(machine_home=machine_home, venv_dir=venv_dir)

    status = _assert_command(
        yoke, project, env, ["qa", "browser", "status", "--json"], 0,
    )
    status_payload = json.loads(status.stdout)
    assert status_payload["daemon"]["status"] == "not_running"

    setup = _assert_command(
        yoke,
        project,
        env,
        ["qa", "browser", "setup", "--dry-run", "--json"],
        0,
    )
    setup_payload = json.loads(setup.stdout)
    assert setup_payload["ok"] is True
    assert setup_payload["dry_run"] is True
    assert setup_payload["readiness"]["daemon"]["status"] == "not_running"
    assert setup_payload["runtime_dir"].endswith("/.yoke/browser-runtime")
