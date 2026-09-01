"""Tests for the deliberate self-host CLI/server paired upgrade."""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from yoke_cli.commands import self_host as commands
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_cli.config.onboard_self_host_server import DockerPrerequisites
from yoke_cli.self_host import bundle
from yoke_cli.self_host import release_target
from yoke_cli.self_host import upgrade
from yoke_contracts.server_image import pinned_server_image


@pytest.fixture()
def initialized_bundle(tmp_path: Path) -> Path:
    target = tmp_path / "server-bundle"
    bundle.write_bundle(
        directory=str(target),
        image="ghcr.io/upyoke/yoke-server:111111111111",
    )
    return target


@pytest.fixture()
def selected_release() -> release_target.ReleaseTarget:
    source_commit = "2" * 40
    return release_target.ReleaseTarget(
        version="0.1.1+launch.400",
        source_commit=source_commit,
        image=pinned_server_image(source_commit),
        base_url="https://distribution.example",
        channel="stable",
        installer_url="https://distribution.example/dist/install.py",
    )


def _plan(directory: Path, target: release_target.ReleaseTarget) -> upgrade.UpgradePlan:
    return upgrade.UpgradePlan(
        directory=directory,
        target=target,
        docker_executable="/usr/bin/docker",
        previous_image="ghcr.io/upyoke/yoke-server:111111111111",
    )


def _completed(command, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def test_channel_target_binds_version_commit_image_and_installer(monkeypatch):
    source_commit = "a" * 40
    seen = []

    def fetch(url: str) -> bytes:
        seen.append(url)
        return json.dumps(
            {
                "schema_version": 3,
                "channel": "stable",
                "version": "0.1.1+launch.401",
                "migration_history": {"source_commit": source_commit},
                "installer": {
                    "python_url": "https://distribution.example/dist/install.py"
                },
            }
        ).encode()

    monkeypatch.setattr(release_target, "_FETCH_BYTES", fetch)
    target = release_target.channel_release_target(
        channel="stable", base_url="https://distribution.example"
    )

    assert seen == ["https://distribution.example/dist/channels/stable.json"]
    assert target.version == "0.1.1+launch.401"
    assert target.source_commit == source_commit
    assert target.image == pinned_server_image(source_commit)


def test_plan_is_read_only_and_names_every_step(
    initialized_bundle, selected_release, monkeypatch
):
    monkeypatch.setattr(
        upgrade.release_target,
        "channel_release_target",
        lambda **_kwargs: selected_release,
    )
    monkeypatch.setattr(
        upgrade,
        "_CHECK_DOCKER",
        lambda: DockerPrerequisites(executable="/usr/bin/docker"),
    )
    before = (initialized_bundle / ".env").read_bytes()

    plan = upgrade.plan_upgrade(directory=str(initialized_bundle))

    assert plan.target == selected_release
    assert plan.previous_image.endswith(":111111111111")
    assert plan.steps == (
        "install Yoke CLI 0.1.1+launch.400 from stable",
        f"replace YOKE_SERVER_IMAGE with {selected_release.image}",
        "run docker compose pull core",
        "run docker compose up -d",
    )
    assert (initialized_bundle / ".env").read_bytes() == before


def test_upgrade_moves_cli_pin_pull_and_restart_as_one_ordered_pair(
    initialized_bundle, selected_release, monkeypatch
):
    calls = []
    env_path = initialized_bundle / ".env"
    env_path.chmod(0o600)
    monkeypatch.setattr(
        upgrade.release_target, "fetch_installer", lambda _target: b"ok"
    )

    def run(command, **kwargs):
        calls.append((tuple(command), kwargs.get("cwd")))
        return _completed(command)

    monkeypatch.setattr(upgrade, "_RUN", run)
    report = upgrade.execute_upgrade(_plan(initialized_bundle, selected_release))

    assert calls[0][0][0] == sys.executable
    assert calls[0][0][2:4] == ("--version", selected_release.version)
    assert calls[1] == (
        ("/usr/bin/docker", "compose", "pull", "core"),
        initialized_bundle,
    )
    assert calls[2] == (("/usr/bin/docker", "compose", "up", "-d"), initialized_bundle)
    env_text = env_path.read_text(encoding="utf-8")
    assert f"YOKE_SERVER_IMAGE={selected_release.image}" in env_text
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
    assert report["version"] == selected_release.version
    assert report["image"] == selected_release.image


def test_installer_failure_preserves_old_pin_and_skips_compose(
    initialized_bundle, selected_release, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        upgrade.release_target, "fetch_installer", lambda _target: b"ok"
    )

    def fail_install(command, **_kwargs):
        calls.append(tuple(command))
        return _completed(command, returncode=7, stderr="resolver unavailable")

    monkeypatch.setattr(upgrade, "_RUN", fail_install)
    with pytest.raises(upgrade.SelfHostUpgradeError) as raised:
        upgrade.execute_upgrade(_plan(initialized_bundle, selected_release))

    assert raised.value.code == "cli-install"
    assert len(calls) == 1
    env_text = (initialized_bundle / ".env").read_text(encoding="utf-8")
    assert "YOKE_SERVER_IMAGE=ghcr.io/upyoke/yoke-server:111111111111" in env_text


def test_pull_failure_keeps_paired_cli_and_pin_with_exact_recovery(
    initialized_bundle, selected_release, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        upgrade.release_target, "fetch_installer", lambda _target: b"ok"
    )

    def fail_pull(command, **_kwargs):
        calls.append(tuple(command))
        if tuple(command[1:]) == ("compose", "pull", "core"):
            return _completed(command, returncode=9, stderr="registry offline")
        return _completed(command)

    monkeypatch.setattr(upgrade, "_RUN", fail_pull)
    with pytest.raises(upgrade.SelfHostUpgradeError) as raised:
        upgrade.execute_upgrade(_plan(initialized_bundle, selected_release))

    assert raised.value.code == "compose-pull"
    assert any("docker compose pull core" in line for line in raised.value.detail_lines)
    assert calls[-1][1:] == ("compose", "pull", "core")
    env_text = (initialized_bundle / ".env").read_text(encoding="utf-8")
    assert f"YOKE_SERVER_IMAGE={selected_release.image}" in env_text


def test_command_previews_and_cancellation_changes_nothing(
    initialized_bundle, selected_release, monkeypatch, capsys
):
    plan = _plan(initialized_bundle, selected_release)
    monkeypatch.setattr(commands.upgrade, "plan_upgrade", lambda **_kwargs: plan)
    monkeypatch.setattr(commands, "_INPUT", lambda _prompt: "cancel")
    monkeypatch.setattr(
        commands.upgrade,
        "execute_upgrade",
        lambda _plan: pytest.fail("cancelled preview must not execute"),
    )

    assert commands.self_host_upgrade(["--dir", str(initialized_bundle)]) == 0
    output = capsys.readouterr().out
    assert "preview (no changes made)" in output
    assert selected_release.image in output
    assert "cancelled; no changes were made" in output


def test_json_command_is_one_structured_completion_receipt(
    initialized_bundle, selected_release, monkeypatch, capsys
):
    plan = _plan(initialized_bundle, selected_release)
    expected = {
        "ok": True,
        "directory": str(initialized_bundle),
        "version": selected_release.version,
        "image": selected_release.image,
    }
    monkeypatch.setattr(commands.upgrade, "plan_upgrade", lambda **_kwargs: plan)
    monkeypatch.setattr(commands.upgrade, "execute_upgrade", lambda _plan: expected)

    assert commands.self_host_upgrade(["--yes", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == expected


def test_upgrade_tool_shaped_resolution():
    resolved = resolve_tool_shaped(["self-host", "upgrade", "--yes"])
    assert resolved is not None
    adapter, remaining = resolved
    assert adapter is commands.self_host_upgrade
    assert remaining == ["--yes"]
