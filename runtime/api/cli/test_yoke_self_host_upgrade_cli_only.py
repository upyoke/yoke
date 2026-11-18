"""Tests for the self-host upgrade when only the CLI is behind the release."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from yoke_cli.commands import self_host as commands
from yoke_cli.config import install_binding
from yoke_cli.self_host import bundle
from yoke_cli.self_host import release_target
from yoke_cli.self_host import upgrade
from yoke_contracts.server_image import pinned_server_image

OLD_IMAGE = "ghcr.io/upyoke/yoke-server:111111111111"


@pytest.fixture(autouse=True)
def packaged_install(monkeypatch, installed_self_host_prerequisites):
    monkeypatch.setattr(
        install_binding, "detect", lambda: {"kind": install_binding.KIND_PACKAGED_WHEEL}
    )


@pytest.fixture()
def selected_release() -> release_target.ReleaseTarget:
    return release_target.ReleaseTarget(
        version="0.2.0.202610140400",
        source_commit="2" * 40,
        image=pinned_server_image("0.2.0.202610140400"),
        base_url="https://distribution.example",
        channel="stable",
        installer_url="https://distribution.example/dist/install.py",
    )


def _bundle(tmp_path: Path, image: str) -> Path:
    target = tmp_path / "server-bundle"
    bundle.write_bundle(admin_name="Ada Lovelace", directory=str(target), image=image)
    return target


def _plan(directory: Path, target, previous_image: str) -> upgrade.UpgradePlan:
    return upgrade.UpgradePlan(
        directory=directory,
        target=target,
        docker_executable="/usr/bin/docker",
        previous_image=previous_image,
    )


@pytest.mark.parametrize("matching", [True, False])
def test_steps_list_only_the_cli_install_when_the_pin_matches(
    tmp_path, selected_release, matching
):
    previous = selected_release.image if matching else OLD_IMAGE
    plan = _plan(tmp_path, selected_release, previous)

    install = "install Yoke CLI 0.2.0.202610140400 from stable"
    if matching:
        assert plan.server_current is True
        assert plan.steps == (install,)
    else:
        assert plan.server_current is False
        assert plan.steps == (
            install,
            f"replace YOKE_SERVER_IMAGE with {selected_release.image}",
            "run docker compose pull core",
            "restart through the private host secret handoff",
        )


@pytest.mark.posix_only(reason="self-host server runs on Linux or WSL2")
def test_matching_pin_installs_cli_without_compose_or_restart(
    tmp_path, selected_release, monkeypatch
):
    directory = _bundle(tmp_path, selected_release.image)
    env_before = (directory / ".env").read_bytes()
    calls = []
    monkeypatch.setattr(
        upgrade.release_target, "fetch_installer", lambda _target: b"ok"
    )

    def run(command, **_kwargs):
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(upgrade, "_RUN", run)
    monkeypatch.setattr(release_target, "_RUN", run)
    monkeypatch.setattr(
        upgrade.runtime,
        "start_bundle",
        lambda **_kwargs: pytest.fail("a current server must not restart"),
    )
    monkeypatch.setattr(
        upgrade.bundle,
        "protect_existing_bundle",
        lambda **_kwargs: pytest.fail("a current server needs no handoff"),
    )

    report = upgrade.execute_upgrade(
        _plan(directory, selected_release, selected_release.image)
    )

    [install] = calls
    assert install[0] == sys.executable
    assert install[2:4] == ("--version", selected_release.version)
    assert not any("compose" in command for command in calls)
    assert (directory / ".env").read_bytes() == env_before
    assert report["server"] == "unchanged"
    assert report["steps"] == [f"install Yoke CLI {selected_release.version} from stable"]
    assert "healthy" not in report


@pytest.mark.posix_only(reason="self-host server runs on Linux or WSL2")
def test_preview_and_summary_say_the_server_stays_running(
    tmp_path, selected_release, monkeypatch, capsys
):
    plan = _plan(tmp_path, selected_release, selected_release.image)
    monkeypatch.setattr(commands.upgrade, "plan_upgrade", lambda **_kwargs: plan)
    monkeypatch.setattr(upgrade, "_CLI_VERSION", lambda: "0.2.0.202610010000")
    monkeypatch.setattr(commands, "_INPUT", lambda _prompt: "upgrade")
    monkeypatch.setattr(
        commands.upgrade,
        "execute_upgrade",
        lambda _plan: {
            "version": selected_release.version,
            "directory": str(tmp_path),
            "image": selected_release.image,
            "server": "unchanged",
        },
    )

    assert commands.self_host_upgrade([]) == 0
    output = capsys.readouterr().out
    assert "  1. install Yoke CLI" in output
    assert "  2." not in output
    assert "it stays running" in output
    assert "the server was already current and kept running" in output
    assert "Compose restart all completed" not in output
