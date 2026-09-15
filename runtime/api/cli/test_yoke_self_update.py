"""Tests for the client-local `yoke update` command."""

from __future__ import annotations

import json
import subprocess

import pytest

from yoke_cli.commands.adapters import self_update as command
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_cli.config import self_update
from yoke_cli.self_host import release_target
from yoke_contracts.install_binding import KIND_PACKAGED_WHEEL, KIND_SOURCE_CHECKOUT
from yoke_contracts.server_image import pinned_server_image


def _completed(command_, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(command_, returncode, stdout, stderr)


def _binding(kind: str, version: str, checkout_root: str | None = None) -> dict:
    return {
        "kind": kind,
        "checkout_root": checkout_root,
        "module_origin": "/wherever/yoke_cli/__init__.py",
        "version": version,
    }


def _target(version: str, channel: str = "stable") -> release_target.ReleaseTarget:
    source_commit = "3" * 40
    return release_target.ReleaseTarget(
        version=version,
        source_commit=source_commit,
        image=pinned_server_image(source_commit),
        base_url="https://distribution.example",
        channel=channel,
        installer_url="https://distribution.example/dist/install.py",
    )


def test_source_checkout_refuses_without_touching_anything(monkeypatch):
    monkeypatch.setattr(
        self_update.install_binding,
        "detect",
        lambda: _binding(KIND_SOURCE_CHECKOUT, "", "/work/yoke"),
    )
    monkeypatch.setattr(
        self_update.release_target,
        "channel_release_target",
        lambda **_kwargs: pytest.fail(
            "must not resolve a channel for a source checkout"
        ),
    )

    with pytest.raises(self_update.SelfUpdateError) as raised:
        self_update.run_update()

    assert "/work/yoke" in str(raised.value)
    assert "source checkout" in str(raised.value)


def test_already_current_skips_reinstall_but_repairs_helper_in_process(monkeypatch):
    monkeypatch.setattr(
        self_update.install_binding,
        "detect",
        lambda: _binding(KIND_PACKAGED_WHEEL, "0.1.1+launch.434"),
    )
    monkeypatch.setattr(
        self_update.shutil, "which", lambda _name: "/usr/local/bin/yoke"
    )
    monkeypatch.setattr(
        self_update.release_target,
        "channel_release_target",
        lambda **_kwargs: _target("0.1.1+launch.434"),
    )
    monkeypatch.setattr(
        self_update.release_target,
        "run_installer",
        lambda *_a, **_k: pytest.fail("already-current update must not reinstall"),
    )
    monkeypatch.setattr(
        self_update.github_git_credentials, "refresh_installed_helper", lambda: True
    )

    result = self_update.run_update()

    assert result == {
        "old_version": "0.1.1+launch.434",
        "new_version": "0.1.1+launch.434",
        "already_current": True,
        "channel": "stable",
        "base_url": "https://distribution.example",
        "credential_helper_refreshed": True,
    }


def test_version_change_reinstalls_and_repairs_via_fresh_binary(monkeypatch):
    monkeypatch.setattr(
        self_update.install_binding,
        "detect",
        lambda: _binding(KIND_PACKAGED_WHEEL, "0.1.1+launch.433"),
    )
    monkeypatch.setattr(
        self_update.shutil, "which", lambda _name: "/usr/local/bin/yoke"
    )
    target = _target("0.1.1+launch.434")
    monkeypatch.setattr(
        self_update.release_target, "channel_release_target", lambda **_kwargs: target
    )
    monkeypatch.setattr(
        self_update.release_target, "fetch_installer", lambda _target: b"installer"
    )
    monkeypatch.setattr(
        self_update.release_target,
        "run_installer",
        lambda _target, _bytes, **_kwargs: _completed(("installer",)),
    )

    calls = []

    def run(command, **_kwargs):
        calls.append(tuple(command))
        if command[1:] == ("--version",):
            return _completed(command, stdout="0.1.1+launch.434\n")
        return _completed(command, stdout=json.dumps({"refreshed": True}))

    monkeypatch.setattr(self_update, "_RUN", run)

    result = self_update.run_update()

    assert calls == [
        ("/usr/local/bin/yoke", "--version"),
        (
            "/usr/local/bin/yoke",
            "github",
            "credential-helper",
            "refresh",
            "--json",
        ),
    ]
    assert result["old_version"] == "0.1.1+launch.433"
    assert result["new_version"] == "0.1.1+launch.434"
    assert result["already_current"] is False
    assert result["credential_helper_refreshed"] is True


def test_installer_failure_raises_with_diagnostic(monkeypatch):
    monkeypatch.setattr(
        self_update.install_binding,
        "detect",
        lambda: _binding(KIND_PACKAGED_WHEEL, "0.1.1+launch.433"),
    )
    monkeypatch.setattr(
        self_update.shutil, "which", lambda _name: "/usr/local/bin/yoke"
    )
    monkeypatch.setattr(
        self_update.release_target,
        "channel_release_target",
        lambda **_kwargs: _target("0.1.1+launch.434"),
    )
    monkeypatch.setattr(
        self_update.release_target, "fetch_installer", lambda _target: b"installer"
    )
    monkeypatch.setattr(
        self_update.release_target,
        "run_installer",
        lambda *_a, **_k: _completed(
            ("installer",), returncode=1, stderr="index unreachable"
        ),
    )

    with pytest.raises(self_update.SelfUpdateError) as raised:
        self_update.run_update()

    assert "index unreachable" in str(raised.value)


def test_command_reports_update_and_repair(monkeypatch, capsys):
    monkeypatch.setattr(
        command.self_update,
        "run_update",
        lambda **_kwargs: {
            "old_version": "0.1.1+launch.433",
            "new_version": "0.1.1+launch.434",
            "already_current": False,
            "channel": "stable",
            "base_url": "https://distribution.example",
            "credential_helper_refreshed": True,
        },
    )

    assert command.update([]) == 0
    output = capsys.readouterr().out
    assert "0.1.1+launch.433 -> 0.1.1+launch.434" in output
    assert "Refreshed the git credential helper" in output


def test_command_error_path_prints_json_and_fails(monkeypatch, capsys):
    monkeypatch.setattr(
        command.self_update,
        "run_update",
        lambda **_kwargs: (_ for _ in ()).throw(
            self_update.SelfUpdateError("distribution unreachable")
        ),
    )

    assert command.update(["--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": False, "error": "distribution unreachable"}


def test_update_tool_shaped_resolution():
    resolved = resolve_tool_shaped(["update", "--channel", "beta"])
    assert resolved is not None
    adapter, remaining = resolved
    assert adapter is command.update
    assert remaining == ["--channel", "beta"]
