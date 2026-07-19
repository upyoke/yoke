"""Product wheel distribution proof for the installable ``yoke`` CLI."""

from __future__ import annotations

import json
import os
import subprocess
from yoke_core.tools.build_release import create_seeded_pip_venv
from pathlib import Path

from runtime.api.cli.project_onboarding_test_helpers import (
    ProjectOnboardApi,
    write_https_config,
)
from runtime.api.cli.product_pack_api import PackApi
from yoke_core.tools import package_index


BASE_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def test_product_wheels_exercise_installer_plan_surfaces(
    tmp_path: Path,
    product_wheelhouse: Path,
) -> None:
    built_wheels = sorted(path.name for path in product_wheelhouse.glob("*.whl"))
    assert any(name.startswith("yoke_cli-") for name in built_wheels)
    assert any(name.startswith("yoke_contracts-") for name in built_wheels)
    assert any(name.startswith("yoke_harness-") for name in built_wheels)
    assert any(name.startswith("yoke_core-") for name in built_wheels)
    assert not any(name.startswith("yoke-") for name in built_wheels)

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
            "yoke-core",
        ],
        cwd=tmp_path,
        timeout=180,
    )
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
                "print(local_universe.LOCAL_DBNAME)"
            ),
        ],
        0,
        "yoke",
    )

    _assert_command(
        yoke,
        project,
        env,
        ["--version"],
        0,
        _wheel_version(product_wheelhouse, "yoke-cli"),
    )
    bare = _assert_command(
        yoke,
        project,
        env,
        [],
        1,
        "yoke onboard --non-interactive",
    )
    assert "yoke --help" in f"{bare.stdout}\n{bare.stderr}"
    top_help = _assert_command(yoke, project, env, ["--help"], 0)
    for surface in (
        "yoke status",
        "yoke onboard",
        "yoke github connect",
        "yoke github status",
        "yoke project create",
        "yoke project import",
        "yoke project install",
        "yoke packs list",
        "yoke packs get",
        "yoke packs update",
        "yoke db read",
        "yoke core build",
        "yoke core status",
        "yoke dev setup",
    ):
        assert surface in top_help.stdout
    status = _assert_command(
        yoke, project, env, ["status", "--json"], 1, "config_missing",
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

    for args, expected in (
        (["onboard", "--help"], "usage: yoke onboard"),
        (["github", "connect", "--help"], "usage: yoke github connect"),
        (["github", "status", "--help"], "usage: yoke github status"),
        (["project", "create", "--help"], "usage: yoke project create"),
        (["project", "import", "--help"], "usage: yoke project import"),
        (["project", "install", "--help"], "usage: yoke project install"),
        (["packs", "list", "--help"], "usage: yoke packs list"),
        (["db", "read", "--help"], "usage: yoke db read"),
        (["core", "build", "--help"], "usage: yoke core build"),
        (["core", "start", "--help"], "--from-checkout"),
        (["core", "upgrade", "--help"], "--from-checkout"),
        (["dev", "setup", "--help"], "usage: yoke dev setup"),
    ):
        helped = _assert_command(yoke, project, env, args, 0, expected)
        if args[:2] in (["core", "start"], ["core", "upgrade"]):
            assert "--build" in helped.stdout
            assert "--pull" not in helped.stdout

    core_status = _assert_command(
        yoke,
        project,
        env,
        ["core", "status", "--json"],
        1,
        "local_core_not_installed",
    )
    core_status_payload = json.loads(core_status.stdout)
    assert core_status_payload["installed"] is False
    assert core_status_payload["image"] is None

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
        cmd[:2] == ["docker", "pull"]
        for cmd in core_start_payload.get("plan") or []
    )

    with PackApi() as api:
        config = write_https_config(tmp_path, "product-token", api.url)
        listing = _assert_command(
            yoke,
            project,
            env,
            [
                "packs", "list", "--project", "sample",
                "--config", str(config), "--json",
            ],
            0,
            "sample-pack",
        )
        listing_payload = json.loads(listing.stdout)
        assert listing_payload["project_slug"] == "sample"
        assert listing_payload["packs"][0]["slug"] == "sample-pack"
        assert listing_payload["packs"][0]["status"] == "available"
        assert api.requests == [{
            "method": "POST",
            "path": "/v1/functions/call",
            "authorization": "Bearer product-token",
            "function": "packs.list",
            "project": "sample",
        }]

    install_project = tmp_path / "install-project"
    install_project.mkdir()
    with ProjectOnboardApi() as api:
        install_config_root = tmp_path / "install-config"
        install_config_root.mkdir()
        config = write_https_config(install_config_root, "product-token", api.url)
        install = _assert_command(
            yoke,
            install_project,
            env,
            [
                "project", "install", str(install_project),
                "--project-id", "41", "--config", str(config), "--json",
            ],
            0,
        )
        install_payload = json.loads(install.stdout)
        assert install_payload["operation"] == "install"
        assert install_payload["project_id"] == 41
        assert (install_project / ".yoke/install-manifest.json").is_file()

    assert sorted(path.name for path in project.iterdir()) == []


def _product_env(*, machine_home: Path, venv_dir: Path) -> dict[str, str]:
    return {
        "HOME": str(machine_home.parent),
        "PATH": f"{venv_dir / 'bin'}:{BASE_PATH}",
        "YOKE_MACHINE_HOME": str(machine_home),
        "PYTHONNOUSERSITE": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
    }


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


def _assert_command(
    yoke: Path,
    cwd: Path,
    env: dict[str, str],
    args: list[str],
    expected_returncode: int | None,
    expected_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    result = _run(
        [str(yoke), *args],
        cwd=cwd,
        env=env,
        check=False,
    )
    if expected_returncode is not None:
        assert result.returncode == expected_returncode, _format_result(result)
    if expected_text is not None:
        assert expected_text in f"{result.stdout}\n{result.stderr}", (
            _format_result(result)
        )
    return result


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    run_env = dict(env) if env is not None else os.environ.copy()
    run_env.pop("PYTHONPATH", None)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=run_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if check:
        assert result.returncode == 0, _format_result(result)
    return result


def _format_result(result: subprocess.CompletedProcess[str]) -> str:
    return (
        f"command failed with {result.returncode}: {result.args!r}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
