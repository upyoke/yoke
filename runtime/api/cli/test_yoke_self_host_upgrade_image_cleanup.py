"""The paired upgrade removes the replaced server image only after a healthy restart."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from yoke_cli.commands import self_host as commands
from yoke_cli.config import install_binding
from yoke_cli.self_host import bundle, release_target, upgrade
from yoke_contracts.server_image import pinned_server_image

OLD_IMAGE = "ghcr.io/upyoke/yoke-server:0.2.0.202611191355"


@pytest.fixture(autouse=True)
def packaged_install(monkeypatch, installed_self_host_prerequisites):
    monkeypatch.setattr(
        install_binding, "detect", lambda: {"kind": install_binding.KIND_PACKAGED_WHEEL}
    )


@pytest.fixture()
def target() -> release_target.ReleaseTarget:
    return release_target.ReleaseTarget(
        version="0.2.0.202611191529",
        source_commit="3" * 40,
        image=pinned_server_image("0.2.0.202611191529"),
        base_url="https://distribution.example",
        channel="stable",
        installer_url="https://distribution.example/dist/install.py",
    )


def _plan(tmp_path: Path, target, previous_image: str) -> upgrade.UpgradePlan:
    directory = tmp_path / "server-bundle"
    bundle.write_bundle(
        admin_name="Ada Lovelace", directory=str(directory), image=previous_image
    )
    (directory / ".env").chmod(0o600)
    return upgrade.UpgradePlan(
        directory=directory,
        target=target,
        docker_executable="/usr/bin/docker",
        previous_image=previous_image,
    )


def _fake_docker(monkeypatch, *, rm_returncode=0, healthy=True):
    calls: list[tuple[str, ...]] = []

    def run(command, **_kwargs):
        calls.append(tuple(command))
        code = rm_returncode if tuple(command[1:3]) == ("image", "rm") else 0
        stderr = f"Error response from daemon: conflict: unable to remove {OLD_IMAGE}"
        return subprocess.CompletedProcess(command, code, "", stderr if code else "")

    def start_bundle(**_kwargs):
        calls.append(("start-bundle",))
        return {"healthy": healthy, **({} if healthy else {"paused": True})}

    monkeypatch.setattr(upgrade.release_target, "fetch_installer", lambda _t: b"ok")
    monkeypatch.setattr(upgrade, "_RUN", run)
    monkeypatch.setattr(release_target, "_RUN", run)
    monkeypatch.setattr(upgrade.runtime, "start_bundle", start_bundle)
    return calls


@pytest.mark.posix_only(reason="self-host server runs on Linux or WSL2")
def test_previous_image_is_removed_only_after_the_healthy_restart(
    tmp_path, target, monkeypatch
):
    calls = _fake_docker(monkeypatch)

    report = upgrade.execute_upgrade(_plan(tmp_path, target, OLD_IMAGE))

    rm = ("/usr/bin/docker", "image", "rm", OLD_IMAGE)
    assert calls.index(rm) == calls.index(("start-bundle",)) + 1
    assert calls[-1] == rm
    assert report["previous_image_removed"] is True
    assert "warnings" not in report


@pytest.mark.posix_only(reason="self-host server runs on Linux or WSL2")
def test_current_server_never_removes_an_image(tmp_path, target, monkeypatch):
    calls = _fake_docker(monkeypatch)

    report = upgrade.execute_upgrade(_plan(tmp_path, target, target.image))

    assert not [call for call in calls if call[1:3] == ("image", "rm")]
    assert report["server"] == "unchanged"
    assert "previous_image_removed" not in report


@pytest.mark.posix_only(reason="self-host server runs on Linux or WSL2")
def test_unhealthy_restart_keeps_the_previous_image_for_rollback(
    tmp_path, target, monkeypatch
):
    calls = _fake_docker(monkeypatch, healthy=False)

    report = upgrade.execute_upgrade(_plan(tmp_path, target, OLD_IMAGE))

    assert not [call for call in calls if call[1:3] == ("image", "rm")]
    assert report["previous_image_removed"] is False
    assert "not reported healthy" in report["previous_image_removal_error"]


@pytest.mark.posix_only(reason="self-host server runs on Linux or WSL2")
def test_failed_removal_warns_with_cause_and_manual_command_and_succeeds(
    tmp_path, target, monkeypatch, capsys
):
    _fake_docker(monkeypatch, rm_returncode=1)
    plan = _plan(tmp_path, target, OLD_IMAGE)
    monkeypatch.setattr(upgrade, "plan_upgrade", lambda **_kwargs: plan)

    code = commands.self_host_upgrade(["--yes", "--json"])

    captured = capsys.readouterr()
    assert code == 0
    assert f"warning: previous server image {OLD_IMAGE} was not removed" in captured.err
    assert "conflict: unable to remove" in captured.err
    assert f"`docker image rm {OLD_IMAGE}`" in captured.err
    report = json.loads(captured.out)
    assert report["ok"] is True
    assert report["previous_image_removed"] is False
    assert "conflict: unable to remove" in report["previous_image_removal_error"]
