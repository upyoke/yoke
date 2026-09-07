"""A candidate relay release verifies as itself under a hostile PYTHONPATH.

The standing relay entrypoint exports PYTHONPATH at the running release's
site-packages, so every child Python it starts inherits that release. These
tests run real interpreters against a real candidate environment with a
conflicting donor on PYTHONPATH: the candidate's own identity must win.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import venv

import pytest

from yoke_cli.config.session_relay_instance import resolve_relay_instance
from yoke_core.tools import session_relay_runtime_install
from yoke_core.tools.session_relay_release import PYTHON_ISOLATION_FLAG
from yoke_core.tools.session_relay_release_install import pin_relay_release


CANDIDATE_RELEASE = "0.1.1+launch.365"
RUNNING_RELEASE = "0.1.1+launch.300"


def _instance(tmp_path: Path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "prod",
                "connections": {
                    "prod": {
                        "transport": "https",
                        "prod": True,
                        "api_url": "https://relay.example.test/api",
                        "credential_source": {
                            "kind": "token_file",
                            "path": str(tmp_path / "token"),
                        },
                    }
                },
                "projects": [],
            }
        ),
        encoding="utf-8",
    )
    return resolve_relay_instance(
        config_path=config,
        environment="prod",
        yoke_home=tmp_path / "state",
    )


def _site_packages(prefix: Path) -> Path:
    return (
        prefix
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )


def _install_metadata(site_packages: Path, release: str) -> None:
    """Write the yoke-core distribution metadata importlib.metadata reads."""
    dist_info = site_packages / f"yoke_core-{release}.dist-info"
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: yoke-core\nVersion: {release}\n",
        encoding="utf-8",
    )


@pytest.fixture
def donor_pythonpath(tmp_path: Path) -> Path:
    """A running release's site-packages, exported the way the relay does."""
    donor = tmp_path / "running-release-packages"
    _install_metadata(donor, RUNNING_RELEASE)
    return donor


def _real_candidate_venv(path: Path) -> None:
    venv.EnvBuilder(with_pip=False, symlinks=True).create(path)


def _installing_runner(donor: Path, argv_log: list[list[str]]):
    """Stand in for pip, then run the real verification the installer built."""

    def run(command, **kwargs):
        argv = list(command)
        argv_log.append(argv)
        candidate = Path(argv[0]).parent.parent
        if "pip" in argv:
            _install_metadata(_site_packages(candidate), CANDIDATE_RELEASE)
            (candidate / "bin" / "yoke").write_text("", encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": str(donor)},
        )

    return run


def test_candidate_verification_reads_the_candidate_not_the_running_release(
    tmp_path: Path, donor_pythonpath: Path
) -> None:
    instance = _instance(tmp_path)
    argv_log: list[list[str]] = []

    status = pin_relay_release(
        instance=instance,
        served_build=f"v{CANDIDATE_RELEASE}",
        create_venv=_real_candidate_venv,
        runner=_installing_runner(donor_pythonpath, argv_log),
    )

    assert status.current
    assert status.pinned_release == CANDIDATE_RELEASE

    verification = next(argv for argv in argv_log if "-c" in argv)
    assert verification[1] == PYTHON_ISOLATION_FLAG

    unisolated = subprocess.run(
        verification[:1] + verification[2:],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(donor_pythonpath)},
    )
    assert unisolated.stdout.strip() == RUNNING_RELEASE, (
        "the donor no longer poisons an unisolated interpreter, so this test "
        "would pass without the isolation flag"
    )


def test_candidate_installation_runs_isolated_from_the_running_release(
    tmp_path: Path, donor_pythonpath: Path
) -> None:
    instance = _instance(tmp_path)
    argv_log: list[list[str]] = []

    pin_relay_release(
        instance=instance,
        served_build=f"v{CANDIDATE_RELEASE}",
        create_venv=_real_candidate_venv,
        runner=_installing_runner(donor_pythonpath, argv_log),
    )

    install = next(argv for argv in argv_log if "pip" in argv)
    assert install[1] == PYTHON_ISOLATION_FLAG


def test_candidate_environment_is_created_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv_log: list[list[str]] = []

    def record(command, **_kwargs):
        argv = list(command)
        argv_log.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(session_relay_runtime_install.subprocess, "run", record)
    session_relay_runtime_install.create_release_venv(
        tmp_path / "candidate", tmp_path / "runtime" / "bin" / "python"
    )

    assert argv_log[0][1] == PYTHON_ISOLATION_FLAG
    assert "venv" in argv_log[0]
