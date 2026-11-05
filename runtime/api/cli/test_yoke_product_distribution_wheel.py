"""Product wheel distribution proof for the installable ``yoke`` CLI."""

from __future__ import annotations

from runtime.api.cli.yoke_product_distribution_wheel_test_support import (
    BASE_PATH as BASE_PATH,
    _assert_command as _assert_command,
    _format_result as _format_result,
    _product_env as _product_env,
    _run as _run,
)


import json
import subprocess
from pathlib import Path

from runtime.api.cli.project_onboarding_test_helpers import (
    ProjectOnboardApi,
    write_https_config,
)
from runtime.api.cli.product_pack_api import PackApi
from yoke_core.tools import package_index


def test_product_wheels_exercise_installer_plan_surfaces(
    tmp_path: Path,
    product_wheelhouse: Path,
    product_venv: Path,
) -> None:
    built_wheels = sorted(path.name for path in product_wheelhouse.glob("*.whl"))
    assert any(name.startswith("yoke_cli-") for name in built_wheels)
    assert any(name.startswith("yoke_contracts-") for name in built_wheels)
    assert any(name.startswith("yoke_harness-") for name in built_wheels)
    assert any(name.startswith("yoke_core-") for name in built_wheels)
    assert not any(name.startswith("yoke-") for name in built_wheels)

    venv_dir = product_venv
    venv_python = venv_dir / "bin" / "python"
    yoke = venv_dir / "bin" / "yoke"
    assert yoke.is_file()

    project = tmp_path / "external-project"
    machine_home = tmp_path / "home" / ".yoke"
    project.mkdir()
    machine_home.mkdir(parents=True)
    env = _product_env(machine_home=machine_home, venv_dir=venv_dir)

    # The engine and its DB driver ship on the channel and install alongside
    # the client; the repo control plane does not.
    _assert_module_presence(
        venv_python,
        project,
        env,
        present=("yoke_core", "psycopg"),
        absent=("runtime",),
    )
    _assert_command(
        venv_python,
        project,
        env,
        [
            "-c",
            (
                "from yoke_core.domain import local_universe; "
                "from yoke_core.domain.install_bundle import server_tree_root; "
                "root = server_tree_root(); "
                "assert (root / '.agents/skills/yoke/SKILL.md').is_file(); "
                "assert (root / 'runtime/harness/claude/agents').is_dir(); "
                "assert all((root / f'runtime/harness/{h}/manifest.json').is_file() for h in ('claude', 'codex', 'cursor')); "
                "print(local_universe.LOCAL_DBNAME)"
            ),
        ],
        0,
        "yoke",
    )

    _assert_command(yoke, project, env, [], 1)
    _assert_command(yoke, project, env, ["project", "--help"], 0)
    status = _assert_command(
        yoke,
        project,
        env,
        ["status", "--json"],
        1,
        "config_missing",
    )
    status_payload = json.loads(status.stdout)
    assert status_payload["ok"] is False
    product_versions = status_payload["runtime"]["package_versions"]
    expected_version = _wheel_version(product_wheelhouse, "yoke-cli")
    assert product_versions == {
        "yoke-cli": expected_version,
        "yoke-contracts": expected_version,
        "yoke-harness": expected_version,
        "yoke-core": expected_version,
    }

    for args in (
        ["project", "create", "--help"],
        ["project", "import", "--help"],
        ["packs", "list", "--help"],
        ["db", "read", "--help"],
        ["core", "build", "--help"],
        ["core", "start", "--help"],
        ["core", "upgrade", "--help"],
        ["dev", "setup", "--help"],
    ):
        _assert_command(yoke, project, env, args, 0)

    core_start = _assert_command(
        yoke,
        project,
        env,
        ["core", "start", "--dry-run", "--json"],
        1,
        "local_core_image_required",
    )
    core_start_payload = json.loads(core_start.stdout)
    assert core_start_payload["dry_run"] is True
    assert core_start_payload["image"] is None
    assert "ghcr.io" not in core_start.stdout
    assert not any(
        cmd[:2] == ["docker", "pull"] for cmd in core_start_payload.get("plan") or []
    )

    with PackApi() as api:
        config = write_https_config(tmp_path, "product-token", api.url)
        listing = _assert_command(
            yoke,
            project,
            env,
            [
                "packs",
                "list",
                "--project",
                "sample",
                "--config",
                str(config),
                "--json",
            ],
            0,
            "sample-pack",
        )
        listing_payload = json.loads(listing.stdout)
        assert listing_payload["project_slug"] == "sample"
        assert listing_payload["packs"][0]["slug"] == "sample-pack"
        assert listing_payload["packs"][0]["status"] == "available"
        assert api.requests == [
            {
                "method": "POST",
                "path": "/v1/functions/call",
                "authorization": "Bearer product-token",
                "function": "packs.list",
                "project": "sample",
            }
        ]

    install_project = tmp_path / "install-project"
    install_project.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(install_project)], check=True
    )
    with ProjectOnboardApi() as api:
        install_config_root = tmp_path / "install-config"
        install_config_root.mkdir()
        config = write_https_config(install_config_root, "product-token", api.url)
        install = _assert_command(
            yoke,
            install_project,
            {**env, "YOKE_MACHINE_HOME": str(config.parent)},
            [
                "project",
                "install",
                str(install_project),
                "--project-id",
                "41",
                "--config",
                str(config),
                "--json",
            ],
            0,
        )
        install_payload = json.loads(install.stdout)
        assert install_payload["operation"] == "install"
        assert install_payload["project_id"] == 41
        assert (install_project / ".yoke/install-manifest.json").is_file()

    assert sorted(path.name for path in project.iterdir()) == []


def _assert_module_presence(
    python: Path,
    cwd: Path,
    env: dict[str, str],
    *,
    present: tuple[str, ...],
    absent: tuple[str, ...],
) -> None:
    code = (
        "import importlib.util; "
        f"missing = [name for name in {present!r} "
        "if importlib.util.find_spec(name) is None]; "
        "assert not missing, ('missing', missing); "
        f"unexpected = [name for name in {absent!r} "
        "if importlib.util.find_spec(name) is not None]; "
        "assert not unexpected, ('unexpected', unexpected)"
    )
    _run([str(python), "-c", code], cwd=cwd, env=env)


def _wheel_version(wheelhouse: Path, package_name: str) -> str:
    for record in package_index.read_wheel_records(wheelhouse):
        if record.canonical_name == package_name:
            return record.version
    raise AssertionError(f"missing wheel for {package_name}")
