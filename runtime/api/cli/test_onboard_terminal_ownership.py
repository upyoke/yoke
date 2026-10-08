"""Setup refuses unsafe jobs and restores an isolated terminal on ownership loss."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from yoke_cli.config import onboard_terminal as terminal


@pytest.mark.skipif(os.name != "posix", reason="POSIX controlling-terminal job control")
@pytest.mark.parametrize("scenario", ["background", "loss", "loss-read", "copy-loss"])
def test_unsafe_terminal_has_named_recovery_and_restored_modes(scenario, tmp_path):
    from runtime.api.cli.onboard_terminal_pty_support import run_pty

    output, result = run_pty(scenario, tmp_path)
    assert result["exit_code"] == 2, output
    assert not result["stops_restored"]
    if scenario == "background":
        assert not result["prepared"]
        assert "setup_terminal_not_foreground" in output
        assert "`fg`" in output
        assert "\x1b[?1000h" not in output
    else:
        assert result["prepared"]
        assert "setup_terminal_ownership_lost" in output
        assert "foreground shell" in output
        for mode in (1000, 1003, 1015, 1006):
            assert f"\x1b[?{mode}h" in output
            assert output.rfind(f"\x1b[?{mode}l") > output.rfind(f"\x1b[?{mode}h")
        assert "Traceback" not in output


@pytest.mark.skipif(os.name != "posix", reason="POSIX controlling-terminal job control")
@pytest.mark.parametrize("scenario", ["foreground", "cancel", "copy", "suspend"])
def test_foreground_handoffs_and_suspend_restore_the_terminal(scenario, tmp_path):
    from runtime.api.cli.onboard_terminal_pty_support import run_pty

    output, result = run_pty(scenario, tmp_path)
    assert result["exit_code"] == (130 if scenario == "cancel" else 0), output
    assert result["prepared"]
    assert "setup_terminal_" not in output
    if scenario == "copy":
        assert "DEMO-CODE" in output
        assert result["handoff"] == "Shown approval code for terminal copying."
    if scenario == "suspend":
        assert result["stops_restored"] == [True]
        assert output.count("\x1b[?1000h") >= 4  # enabled twice per start


def test_windows_uses_its_native_console_without_posix_calls(monkeypatch):
    monkeypatch.setattr(terminal.os, "name", "nt")
    terminal.require_foreground_terminal(SimpleNamespace())
    from yoke_cli.config.onboard_terminal_driver import run_wizard_app

    calls = []
    run_wizard_app(SimpleNamespace(run=lambda: calls.append("native")))
    assert calls == ["native"]


def test_missing_ownership_capability_teaches_noninteractive_recovery(monkeypatch):
    monkeypatch.setattr(terminal.os, "name", "posix")
    with pytest.raises(
        terminal.SetupTerminalError, match="setup_terminal_ownership_unavailable"
    ) as failure:
        terminal.require_foreground_terminal(SimpleNamespace())
    assert "--non-interactive" in str(failure.value)


@pytest.mark.parametrize("mode", ["--non-interactive", "--json"])
def test_intentional_noninteractive_setup_bypasses_terminal_checks(
    mode, tmp_path, monkeypatch, capsys
):
    from yoke_cli.commands.adapters import onboard, onboard_interactive

    monkeypatch.setattr(
        onboard_interactive,
        "require_foreground_terminal",
        lambda: pytest.fail(
            "noninteractive setup attempted terminal ownership validation"
        ),
    )
    assert onboard.run([mode, "--config", str(tmp_path / "config.json")]) == 2
    assert "setup_terminal_" not in capsys.readouterr().err
    assert not (tmp_path / "config.json").exists()
