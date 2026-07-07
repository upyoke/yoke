"""Wheel-level smoke for the ``yoke-cli`` product package with the engine present.

The engine wheel (yoke-core) installs alongside the client on every machine;
this smoke proves the client behaves identically with the engine importable —
present but inert.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from runtime.api.product_boundary_isolation import write_sitecustomize
from yoke_core.tools import package_index
from yoke_core.tools.build_release import create_seeded_pip_venv


BASE_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def test_yoke_cli_product_wheel_runs_from_fixture_checkout(
    tmp_path: Path,
    product_wheelhouse: Path,
) -> None:
    venv_dir = tmp_path / "venv"
    create_seeded_pip_venv(venv_dir, system_site_packages=True)
    venv_python = venv_dir / "bin" / "python"
    yoke = venv_dir / "bin" / "yoke"
    _run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--ignore-installed",
            "--no-index",
            "--find-links",
            str(product_wheelhouse),
            "yoke-cli",
            "yoke-core",
        ],
        cwd=tmp_path,
        timeout=180,
    )
    assert yoke.is_file()

    checkout = tmp_path / "fixture-checkout"
    machine_home = tmp_path / "home" / ".yoke"
    (checkout / ".yoke").mkdir(parents=True)
    machine_home.mkdir(parents=True)
    (checkout / ".yoke" / "board-art").write_text("# fixture\n", encoding="utf-8")
    sitecustomize_dir = write_sitecustomize(
        tmp_path,
        repo_root=Path(__file__).resolve().parents[2],
        allowed_repo_paths=(),
    )
    env = _product_env(
        machine_home=machine_home,
        venv_dir=venv_dir,
        sitecustomize_dir=sitecustomize_dir,
    )

    # Engine present: the wheel channel ships yoke-core to every machine.
    import_check = _run(
        [
            str(venv_python),
            "-c",
            "import importlib.util; "
            "assert importlib.util.find_spec('yoke_core') is not None",
        ],
        cwd=checkout,
        env=env,
    )
    assert import_check.stdout == ""

    version = _run([str(yoke), "--version"], cwd=checkout, env=env)
    assert version.stdout.strip() == _wheel_version(product_wheelhouse, "yoke-cli")

    help_result = _run([str(yoke), "--help"], cwd=checkout, env=env)
    assert "yoke status" in help_result.stdout
    assert "yoke core build" in help_result.stdout
    assert "yoke core status" in help_result.stdout
    assert "yoke core install" not in help_result.stdout
    assert "yoke config example" in help_result.stdout
    assert "yoke board art variant create" in help_result.stdout

    core_status = _run(
        [str(yoke), "core", "status", "--json"],
        cwd=checkout,
        env=env,
        check=False,
    )
    assert core_status.returncode == 1, _format_result(core_status)
    core_payload = json.loads(core_status.stdout)
    assert core_payload["ok"] is False
    assert core_payload["installed"] is False
    assert core_payload["image"] is None
    assert core_payload["api"]["url"] == "http://127.0.0.1:8765"
    assert "docker" in core_payload["runtime"]
    assert "local_core_not_installed" in _issue_codes(core_payload)

    status = _run(
        [str(yoke), "status", "--json"],
        cwd=checkout,
        env=env,
        check=False,
    )
    assert status.returncode == 1, _format_result(status)
    status_payload = json.loads(status.stdout)
    assert status_payload["ok"] is False
    assert _issue_codes(status_payload) >= {
        "config_missing",
        "connections_required",
    }

    config_example = _run([str(yoke), "config", "example"], cwd=checkout, env=env)
    example_payload = json.loads(config_example.stdout)
    assert example_payload["schema_version"] == 1
    assert "connections" in example_payload

    variant = _run(
        [
            str(yoke),
            "board",
            "art",
            "variant",
            "create",
            "--ascii",
            str(checkout),
            "--display-name",
            "Smoke",
            "--seed",
            "wheel-smoke",
            "--json",
        ],
        cwd=checkout,
        env=env,
    )
    variant_payload = json.loads(variant.stdout)
    assert variant_payload["kind"] == "ASCII"
    assert variant_payload["applied"] is False
    assert variant_payload["repo_root"] == str(checkout)
    assert variant_payload["board_art_path"] == str(checkout / ".yoke" / "board-art")
    assert variant_payload["text"].strip()


def _product_env(
    *,
    machine_home: Path,
    venv_dir: Path,
    sitecustomize_dir: Path,
) -> dict[str, str]:
    return {
        "HOME": str(machine_home.parent),
        "PATH": f"{venv_dir / 'bin'}:{BASE_PATH}",
        "PYTHONPATH": str(sitecustomize_dir),
        "YOKE_MACHINE_HOME": str(machine_home),
        "PYTHONNOUSERSITE": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
    }


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    run_env = dict(env) if env is not None else os.environ.copy()
    if env is None:
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


def _issue_codes(payload: dict[str, object]) -> set[str]:
    return {
        str(issue.get("code") or "")
        for issue in payload.get("issues") or []
        if isinstance(issue, dict)
    }


def _wheel_version(wheelhouse: Path, package_name: str) -> str:
    for record in package_index.read_wheel_records(wheelhouse):
        if record.canonical_name == package_name:
            return record.version
    raise AssertionError(f"missing wheel for {package_name}")
