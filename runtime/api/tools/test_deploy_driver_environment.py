"""Pinned drivers use candidate dependencies rather than the launching tool's."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from yoke_core.domain.deploy_pipeline_pinned_source import (
    DeployPinnedSourceError,
    PinnedDriverSource,
)
from yoke_core.domain import deploy_pipeline_pinned_driver as driver


def _locked_candidate(root: Path) -> None:
    wheel = root / "candidate_only_dependency-1.0-py3-none-any.whl"
    metadata = "candidate_only_dependency-1.0.dist-info"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("candidate_only_dependency.py", "VALUE = 'candidate'\n")
        archive.writestr(
            f"{metadata}/METADATA",
            "Metadata-Version: 2.1\nName: candidate-only-dependency\nVersion: 1.0\n",
        )
        archive.writestr(
            f"{metadata}/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(f"{metadata}/RECORD", "")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "candidate"\nversion = "1.0"\n'
        'requires-python = ">=3.11"\ndependencies = ["candidate-only-dependency"]\n'
        "[tool.uv]\npackage = false\n[tool.uv.sources]\n"
        f'candidate-only-dependency = {{path = "{wheel.name}"}}\n',
    )
    subprocess.run(
        ["uv", "lock", "--offline", "--project", str(root)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_candidate_dependency_missing_from_driver_is_available_to_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _locked_candidate(tmp_path)
    missing = subprocess.run(
        [sys.executable, "-c", "import candidate_only_dependency"],
        capture_output=True,
        text=True,
    )
    assert missing.returncode != 0
    lock = (tmp_path / "uv.lock").read_bytes()
    monkeypatch.setattr(
        driver,
        "prepare_self_deploy_driver",
        lambda _: PinnedDriverSource(tmp_path, "candidate-sha"),
    )
    ambient = tmp_path / "ambient"
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(ambient))
    monkeypatch.setenv("UV_NO_SYNC", "1")
    env = driver.child_environment("run-1")
    assert env is not None
    command = driver.pinned_driver_command("candidate_only_dependency", [], env)
    child = subprocess.run(
        [command[0], "-c", "import candidate_only_dependency as d; print(d.VALUE)"],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert child.stdout.strip() == "candidate"
    assert Path(env["VIRTUAL_ENV"]) == tmp_path / ".venv"
    assert not ambient.exists()
    assert (tmp_path / "uv.lock").read_bytes() == lock


@pytest.mark.parametrize("failure", ["exit", "missing-uv", "timeout", "missing-python"])
def test_environment_preparation_refuses_with_same_run_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / "uv.lock").touch()

    def sync(*args, **kwargs):
        if failure == "missing-uv":
            raise FileNotFoundError("uv")
        if failure == "timeout":
            raise subprocess.TimeoutExpired("uv", 300)
        return subprocess.CompletedProcess(
            args[0], 1 if failure == "exit" else 0, "", "sync refused"
        )

    monkeypatch.setattr(driver.subprocess, "run", sync)
    with pytest.raises(
        DeployPinnedSourceError, match="DEPLOY-DRIVER-ENVIRONMENT"
    ) as raised:
        driver.environment_for_pinned_driver(PinnedDriverSource(tmp_path, "sha"), {})
    assert "re-drive the same run" in str(raised.value)
    assert "uv sync --frozen --no-dev" in str(raised.value)


def test_relayed_driver_keeps_installed_interpreter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(driver, "prepare_self_deploy_driver", lambda _: None)
    assert driver.child_environment("run-1") is None
    assert driver.pinned_driver_command("engine", [], None)[0] == sys.executable


def test_environment_requires_a_checkout_owned_lock_and_venv(tmp_path: Path) -> None:
    prepared = PinnedDriverSource(tmp_path, "sha")
    with pytest.raises(
        DeployPinnedSourceError, match="lacks pyproject.toml or uv.lock"
    ):
        driver.environment_for_pinned_driver(prepared, {})
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / "uv.lock").touch()
    (tmp_path / ".venv").symlink_to(tmp_path / "foreign")
    with pytest.raises(
        DeployPinnedSourceError, match="replace it with a local environment"
    ):
        driver.environment_for_pinned_driver(prepared, {})
