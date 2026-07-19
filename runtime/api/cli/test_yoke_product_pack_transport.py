"""Pack get/update proof through the installed CLI's HTTPS transport."""

from __future__ import annotations

import json
from pathlib import Path

from runtime.api.cli.product_pack_api import PackApi
from runtime.api.cli.project_onboarding_test_helpers import write_https_config
from runtime.api.cli.test_yoke_product_distribution_wheel import (
    _assert_command,
    _product_env,
    _run,
)
from yoke_core.tools.build_release import create_seeded_pip_venv


def test_packaged_cli_gets_and_updates_customized_pack_over_https(
    tmp_path: Path,
    product_wheelhouse: Path,
) -> None:
    venv_dir = tmp_path / "venv"
    create_seeded_pip_venv(venv_dir)
    python = venv_dir / "bin" / "python"
    yoke = venv_dir / "bin" / "yoke"
    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            str(product_wheelhouse),
            "yoke-cli",
            "yoke-harness",
            "yoke-core",
        ],
        cwd=tmp_path,
        timeout=180,
    )
    project = tmp_path / "external-project"
    project.mkdir()
    machine_home = tmp_path / "home" / ".yoke"
    machine_home.mkdir(parents=True)
    env = _product_env(machine_home=machine_home, venv_dir=venv_dir)

    with PackApi() as api:
        config = write_https_config(tmp_path, "product-token", api.url)
        payload = json.loads(config.read_text(encoding="utf-8"))
        payload["projects"] = [{
            "checkout": str(project.resolve()),
            "project_id": 41,
            "env": "prod",
        }]
        config.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        preview_get = _pack_command(
            yoke, project, env, config, "get", "--version", "1.0.0",
        )
        assert preview_get["applied"] is False
        assert preview_get["plans"][0]["plan"]["creates"] == ["sample-pack.txt"]
        assert not (project / "sample-pack.txt").exists()

        applied_get = _pack_command(
            yoke,
            project,
            env,
            config,
            "get",
            "--version",
            "1.0.0",
            "--apply",
        )
        assert applied_get["applied"] is True
        project_file = project / "sample-pack.txt"
        project_file.write_text(
            project_file.read_text(encoding="utf-8") + "project-owned\n",
            encoding="utf-8",
        )

        preview_update = _pack_command(
            yoke, project, env, config, "update",
        )
        assert preview_update["applied"] is False
        assert preview_update["conflict_count"] == 0
        assert project_file.read_text(encoding="utf-8").startswith("base\n")

        applied_update = _pack_command(
            yoke, project, env, config, "update", "--apply",
        )
        assert applied_update["applied"] is True
        assert project_file.read_text(encoding="utf-8") == (
            "base-v2\ncustom-slot\nproject-owned\n"
        )
        receipt = json.loads(
            (project / ".yoke" / "packs.json").read_text(encoding="utf-8")
        )
        assert receipt["packs"]["sample-pack"]["version"] == "1.1.0"
        functions = [request["function"] for request in api.requests]
        assert functions.count("packs.bundle.get") == 6
        assert functions.count("packs.project.report") == 2


def _pack_command(
    yoke: Path,
    project: Path,
    env: dict[str, str],
    config: Path,
    operation: str,
    *extra: str,
) -> dict:
    result = _assert_command(
        yoke,
        project,
        env,
        [
            "packs",
            operation,
            "sample-pack",
            ".",
            "--project",
            "sample",
            "--config",
            str(config),
            *extra,
            "--json",
        ],
        0,
    )
    return json.loads(result.stdout)
