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
        self_update.github_repo_helper_reconnect,
        "restore_missing_bundle",
        lambda _config_path: {"configured": True, "repaired": True},
    )

    result = self_update.run_update()

    assert result == {
        "old_version": "0.1.1+launch.434",
        "new_version": "0.1.1+launch.434",
        "already_current": True,
        "channel": "stable",
        "base_url": "https://distribution.example",
        "credential_helper_configured": True,
        "credential_helper_repaired": True,
        "credential_helper_error": None,
    }


def _stub_version_change(
    monkeypatch, *, installer_rc: int = 0, installer_stderr: str = ""
) -> None:
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
        lambda _target, _bytes, **_kwargs: _completed(
            ("installer",), returncode=installer_rc, stderr=installer_stderr
        ),
    )


def test_version_change_reinstall_success_has_no_independent_repair_signal(
    monkeypatch,
):
    """The installer performs and enforces its own credential-helper repair
    as part of a successful run; this module must not repeat it, and a
    successful reinstall carries no independent repair signal to report."""
    _stub_version_change(monkeypatch)
    calls = []

    def run(command, **_kwargs):
        calls.append(tuple(command))
        return _completed(command, stdout="0.1.1+launch.434\n")

    monkeypatch.setattr(self_update, "_RUN", run)

    result = self_update.run_update()

    # No second subprocess call for the repair: only the version probe runs.
    assert calls == [("/usr/local/bin/yoke", "--version")]
    assert result["old_version"] == "0.1.1+launch.433"
    assert result["new_version"] == "0.1.1+launch.434"
    assert result["already_current"] is False
    assert result["credential_helper_configured"] is None
    assert result["credential_helper_repaired"] is None
    assert result["credential_helper_error"] is None


def test_version_change_installer_repair_failure_raises_via_exit_code(monkeypatch):
    """A credential-helper repair failure fails the installer itself (the
    same way a product-boundary-audit failure does), so a non-zero exit
    from a repair failure must reach `yoke update` as a real failure too."""
    _stub_version_change(
        monkeypatch,
        installer_rc=1,
        installer_stderr="credential helper repair failed: permission denied",
    )

    with pytest.raises(self_update.SelfUpdateError) as raised:
        self_update.run_update()

    assert "permission denied" in str(raised.value)


def test_stale_version_after_successful_installer_run_raises(monkeypatch):
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
        lambda *_a, **_k: _completed(("installer",)),
    )
    # The installer reported success, but the freshly resolved `yoke` binary
    # still reports the OLD version -- a silent installer no-op/failure this
    # must not mistake for "already current" (that branch never reinstalls).
    monkeypatch.setattr(
        self_update,
        "_RUN",
        lambda command, **_k: _completed(command, stdout="0.1.1+launch.433\n"),
    )

    with pytest.raises(self_update.SelfUpdateError) as raised:
        self_update.run_update()

    assert "0.1.1+launch.433" in str(raised.value)
    assert "0.1.1+launch.434" in str(raised.value)


def test_credential_repair_failure_surfaces_distinctly_from_a_legitimate_no_op(
    monkeypatch,
):
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
        self_update.github_repo_helper_reconnect,
        "restore_missing_bundle",
        lambda _config_path: {
            "configured": True,
            "repaired": False,
            "error": "permission denied",
        },
    )

    result = self_update.run_update()

    assert result["credential_helper_configured"] is True
    assert result["credential_helper_repaired"] is False
    assert result["credential_helper_error"] == "permission denied"


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
            "credential_helper_configured": True,
            "credential_helper_repaired": True,
            "credential_helper_error": None,
        },
    )

    assert command.update([]) == 0
    output = capsys.readouterr().out
    assert "0.1.1+launch.433 -> 0.1.1+launch.434" in output
    assert "Rebuilt the git credential helper bundle" in output


def test_command_surfaces_a_repair_failure_as_a_warning_and_non_zero_exit(
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        command.self_update,
        "run_update",
        lambda **_kwargs: {
            "old_version": "0.1.1+launch.433",
            "new_version": "0.1.1+launch.434",
            "already_current": False,
            "channel": "stable",
            "base_url": "https://distribution.example",
            "credential_helper_configured": True,
            "credential_helper_repaired": False,
            "credential_helper_error": "permission denied",
        },
    )

    assert command.update([]) == 1
    output = capsys.readouterr().out
    assert "0.1.1+launch.433 -> 0.1.1+launch.434" in output
    assert "warning: git credential helper repair failed: permission denied" in output


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
