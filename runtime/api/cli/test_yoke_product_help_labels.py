"""Product-wheel help labels for non-product command surfaces."""

from __future__ import annotations

from yoke_core.tools.build_release import create_seeded_pip_venv
from pathlib import Path

from runtime.api.cli.test_yoke_product_distribution_wheel import (
    _assert_command,
    _product_env,
    _run,
)


def test_product_wheel_help_labels_non_product_surfaces(
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

    top_help = _assert_command(yoke, project, env, ["--help"], 0)
    assert "yoke dev setup [source-dev/admin]" in top_help.stdout
    assert "yoke qa browser run [client-local]" in top_help.stdout
    assert not any(
        line.startswith("    yoke status [")
        for line in top_help.stdout.splitlines()
    )

    for args, expected in (
        (["dev", "--help"], "yoke dev setup [source-dev/admin]"),
        (["agents", "--help"], "yoke agents render [source-dev/admin]"),
        (["packets", "--help"], "yoke packets check [source-dev/admin]"),
        (["merge", "--help"], "yoke merge audit [source-dev/admin]"),
        (["resync", "--help"], "source-dev/admin command surface"),
        (["project", "--help"], "yoke project install"),
        (["projects", "--help"], "yoke projects create"),
        (["strategy", "--help"], "yoke strategy doc list"),
        (["qa", "browser", "--help"], "yoke qa browser run [client-local]"),
        (
            ["github-actions", "--help"],
            "yoke github-actions secret set [source-dev/admin]",
        ),
    ):
        _assert_command(yoke, project, env, args, 0, expected)
