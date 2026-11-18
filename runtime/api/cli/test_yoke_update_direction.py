"""`yoke update` names its direction and whether a pin or the channel chose it."""

from __future__ import annotations

import json
import subprocess

import pytest

from yoke_cli.commands.adapters import self_update as command
from yoke_cli.config import distribution, self_update
from yoke_cli.self_host import release_target
from yoke_contracts.install_binding import KIND_PACKAGED_WHEEL
from yoke_contracts.server_image import pinned_server_image

INSTALLED = "0.2.0.202611181739"
PREVIOUS = "0.2.0.202611181637"
LATEST = "0.2.0.202611181900"


@pytest.fixture(autouse=True)
def recorded_distribution(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(tmp_path / "config.json"))
    distribution.save(origin="https://distribution.example", channel="latest")


def _install_stubs(monkeypatch, *, installed: str, channel_version: str) -> list:
    """Stub the packaged install, channel and installer; return installed targets."""
    installs: list = []
    monkeypatch.setattr(
        self_update.install_binding,
        "detect",
        lambda: {
            "kind": KIND_PACKAGED_WHEEL,
            "checkout_root": None,
            "module_origin": "/wherever/yoke_cli/__init__.py",
            "version": installed,
        },
    )
    monkeypatch.setattr(self_update.shutil, "which", lambda _name: "/bin/yoke")
    monkeypatch.setattr(
        self_update.release_target,
        "channel_release_target",
        lambda **kwargs: release_target.ReleaseTarget(
            version=channel_version,
            source_commit="3" * 40,
            image=pinned_server_image(channel_version),
            base_url=kwargs["base_url"],
            channel=kwargs["channel"],
            installer_url="https://distribution.example/dist/install.py",
        ),
    )
    monkeypatch.setattr(
        self_update.release_target, "fetch_installer", lambda _target: b"installer"
    )

    def run_installer(target, _bytes, **_kwargs):
        installs.append(target)
        return subprocess.CompletedProcess(("installer",), 0, "", "")

    monkeypatch.setattr(self_update.release_target, "run_installer", run_installer)
    monkeypatch.setattr(
        self_update,
        "_RUN",
        lambda cmd, **_k: subprocess.CompletedProcess(
            cmd, 0, f"{installs[-1].version}\n", ""
        ),
    )
    return installs


def _run(args: list[str], capsys) -> tuple[int, str]:
    code = command.update(args)
    return code, capsys.readouterr().out


def test_pinned_downgrade_says_downgraded_and_names_the_channel_latest(
    monkeypatch, capsys
):
    _install_stubs(monkeypatch, installed=INSTALLED, channel_version=LATEST)

    code, out = _run(["--channel", "latest", "--version", PREVIOUS], capsys)

    assert code == 0
    assert out.splitlines()[0] == (
        f"Downgraded Yoke {INSTALLED} -> {PREVIOUS} "
        f"(pinned; latest on latest is {LATEST})."
    )
    assert "Updated" not in out


def test_pinned_downgrade_json_carries_direction_and_pin(monkeypatch, capsys):
    _install_stubs(monkeypatch, installed=INSTALLED, channel_version=LATEST)

    code, out = _run(["--version", PREVIOUS, "--json"], capsys)

    payload = json.loads(out)
    assert code == 0
    assert payload["direction"] == "downgrade"
    assert payload["pinned"] is True
    assert payload["channel"] == "latest"
    assert payload["channel_version"] == LATEST
    assert payload["new_version"] == PREVIOUS


def test_pinned_upgrade_says_pinned_without_the_channel(monkeypatch, capsys):
    _install_stubs(monkeypatch, installed=PREVIOUS, channel_version=LATEST)

    code, out = _run(["--version", INSTALLED], capsys)

    assert code == 0
    assert out.splitlines()[0] == f"Updated Yoke {PREVIOUS} -> {INSTALLED} (pinned)."
    assert "(latest)" not in out


def test_channel_update_names_the_channel(monkeypatch, capsys):
    installs = _install_stubs(monkeypatch, installed=INSTALLED, channel_version=LATEST)

    code, out = _run(["--json"], capsys)
    payload = json.loads(out)
    assert code == 0
    assert payload["direction"] == "upgrade"
    assert payload["pinned"] is False
    assert installs[-1].version == LATEST

    _install_stubs(monkeypatch, installed=INSTALLED, channel_version=LATEST)
    code, out = _run([], capsys)
    assert code == 0
    assert out.splitlines()[0] == f"Updated Yoke {INSTALLED} -> {LATEST} (latest)."


def test_unorderable_pin_refuses_before_installing(monkeypatch, capsys):
    installs = _install_stubs(monkeypatch, installed=INSTALLED, channel_version=LATEST)

    code, out = _run(["--version", "nightly"], capsys)

    assert code == 1
    assert out.startswith("yoke update: cannot order")
    assert "BASE.YYYYMMDDHHMM" in out
    assert installs == []


def _reported(**overrides) -> dict:
    result = {
        "old_version": "0.2.0.202610140433",
        "new_version": "0.2.0.202610140434",
        "already_current": False,
        "direction": "upgrade",
        "pinned": False,
        "channel": "stable",
        "channel_version": "0.2.0.202610140434",
        "base_url": "https://distribution.example",
        "credential_helper_configured": True,
        "credential_helper_repaired": True,
        "credential_helper_error": None,
        "project_refresh": {"status": "not_installed"},
    }
    return {**result, **overrides}


def test_command_reports_update_and_repair(monkeypatch, capsys):
    monkeypatch.setattr(command.self_update, "run_update", lambda **_k: _reported())

    code, out = _run([], capsys)

    assert code == 0
    assert "0.2.0.202610140433 -> 0.2.0.202610140434 (stable)" in out
    assert "Rebuilt the git credential helper bundle" in out


def test_command_surfaces_a_repair_failure_as_a_warning_and_non_zero_exit(
    monkeypatch, capsys
):
    monkeypatch.setattr(
        command.self_update,
        "run_update",
        lambda **_k: _reported(
            credential_helper_repaired=False,
            credential_helper_error="permission denied",
        ),
    )

    code, out = _run([], capsys)

    assert code == 1
    assert "0.2.0.202610140433 -> 0.2.0.202610140434" in out
    assert "warning: git credential helper repair failed: permission denied" in out
