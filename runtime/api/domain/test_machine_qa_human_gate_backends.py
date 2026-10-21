"""Operator gates through both macOS terminal backends and Linux."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.domain.machine_qa_terminal_recipe_test_support import (
    completed,
    recipe,
)
from runtime.api.domain.scripted_mac_host_test_support import ScriptedMacHost
from yoke_harness.machine_account_chooser import DeclaredAccounts
from yoke_core.domain import ssh_mac_terminal_recipe
from yoke_core.domain.ssh_linux_terminal_recipe import execute_linux_recipe
from yoke_core.domain.ssh_mac_terminal_recipe import execute_terminal_recipe
from yoke_harness import ssh_linux_browser_approval

SCREEN = "Match code: K7F2\nMachine connected.\n"


def _config(mode: str, purpose: str = "password_entry") -> dict:
    config = recipe(mode=mode)
    config["post_checks"] = []
    config["expected_text"] = ["Machine connected."]
    config["actions"] = [
        {
            "step": "person-acts",
            "keys": [],
            "capture": False,
            "operator_gate": "human_action",
            "human_purpose": purpose,
            "completion_text": ["Machine connected."],
            "gate_timeout_seconds": 900.0,
        }
    ]
    return config


def _assert_human_step(step: dict, location: str) -> None:
    assert step["key"] == "person-acts"
    assert step["gate_evidence"]["self_approving"] is False
    assert step["gate_evidence"]["human_purpose"] == "password_entry"
    assert location in step["gate_evidence"]["terminal_location"]


def test_tmux_backend_waits_without_sending_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys: list[object] = []
    for module in ("ssh_mac_terminal_recipe", "machine_qa_human_gate"):
        monkeypatch.setattr(
            f"yoke_core.domain.{module}.send_recipe_keys",
            lambda *_a, **kw: keys.append(kw["keys"]) or True,
        )
        monkeypatch.setattr(
            f"yoke_core.domain.{module}.capture_recipe_transcript",
            lambda *_a, **_kw: SCREEN,
        )
    for name, value in {
        "detect_terminal_backend": lambda _run: "tmux",
        "open_terminal_window": lambda _run, command: 7,
        "close_terminal_session": lambda *_a, **_kw: None,
        "close_terminal_window": lambda *_a, **_kw: None,
        "read_recipe_exit_code": lambda *_a, **_kw: 0,
    }.items():
        monkeypatch.setattr(ssh_mac_terminal_recipe, name, value)
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_human_gate.read_recipe_exit_code",
        lambda *_a, **_kw: None,
    )
    monkeypatch.setattr(ssh_mac_terminal_recipe.time, "sleep", lambda _s: None)

    result = ssh_mac_terminal_recipe._run_interactive_recipe(
        lambda command, **_kw: completed(command),
        yoke_bin="yoke",
        entry_surface="yoke setup",
        required_completion="person-acts",
        config=_config("terminal-multiplexer"),
        evidence_parent=tmp_path,
        secret_values=(),
        staged=[],
        terminal_size=None,
        progress_callback=None,
        allowed_operator_urls=(),
        declared_accounts=DeclaredAccounts(),
    )

    assert result.ok, result.evidence
    assert keys == []
    _assert_human_step(result.evidence["steps"][0], "tmux attach-session -t yoke-qa-")


class _TerminalAppHost(ScriptedMacHost):
    def reply(self, command: str) -> str | None:
        if "return contents of selected tab" in command:
            return SCREEN
        if 'tell application "System Events"' in command:
            return "true"
        if command.startswith("cat /tmp/yoke-qa-"):
            return "0\n"
        return None


def test_terminal_app_backend_waits_without_sending_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_terminal_app_recipe.uuid4",
        lambda: SimpleNamespace(hex="b" * 32),
    )
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_terminal_app_recipe.time.sleep",
        lambda _seconds: None,
    )
    host = _TerminalAppHost()

    result = execute_terminal_recipe(
        host,
        yoke_bin="yoke",
        upload_bytes=lambda _path, _content: True,
        entry_surface="yoke setup",
        required_completion="person-acts",
        config=_config("terminal"),
        evidence_parent=tmp_path,
        secret_values=(),
    )

    assert result.ok, result.evidence
    # Only cleanup's interrupt reaches the window; the gate itself sends nothing.
    key_scripts = [command for command in host.commands if "key code" in command]
    assert len(key_scripts) == 1 and "using {control down}" in key_scripts[0]
    assert not any('tell application "Safari"' in command for command in host.commands)
    _assert_human_step(result.evidence["steps"][0], "Terminal.app window")


def _linux(monkeypatch: pytest.MonkeyPatch, events: list) -> SimpleNamespace:
    class Terminal:
        session = "linux-session"

        def __init__(self, control):
            pass

        def open(self, entry_surface, size, environment=None):
            events.append(("open", environment))
            return True

        def transcript(self):
            return SCREEN + "__YOKE_EXIT_0\n"

        def close(self):
            return True

    monkeypatch.setattr(
        "yoke_core.domain.ssh_linux_terminal_recipe.LinuxTerminal", Terminal
    )
    monkeypatch.setattr(
        "yoke_core.domain.ssh_linux_operator_gate.send_recipe_keys",
        lambda *_a, **kw: events.append(("keys", kw["keys"])) or True,
    )
    monkeypatch.setattr(
        "yoke_core.domain.ssh_linux_terminal_recipe.time.sleep", lambda _s: None
    )
    return SimpleNamespace(
        secret_values=(),
        path_state=SimpleNamespace(yoke_bin="/home/qa/.local/bin/yoke"),
        _upload_bytes=lambda *a: True,
        _run=lambda command, **kw: (
            events.append(("run", command)) or completed(command)
        ),
    )


def test_linux_backend_waits_without_sending_keys_or_a_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list = []

    def no_browser(control):
        raise AssertionError("approval and invite steps need no browser")

    monkeypatch.setattr(ssh_linux_browser_approval, "ensure_desktop", no_browser)
    result = execute_linux_recipe(
        _linux(monkeypatch, events),
        entry_surface="yoke setup",
        required_completion="person-acts",
        config=_config("terminal-multiplexer"),
        size=(120, 40),
    )
    assert result.ok, result.evidence
    assert [event for event in events if event[0] != "run"] == [("open", None)]
    _assert_human_step(
        result.evidence["steps"][0], "tmux attach-session -t linux-session"
    )


def test_linux_owner_approval_runs_the_cli_as_the_fixture_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list = []

    def no_browser(control):
        raise AssertionError("owner approval needs no browser")

    monkeypatch.setattr(ssh_linux_browser_approval, "ensure_desktop", no_browser)
    config = _config("terminal-multiplexer")
    config["actions"][0] = {
        "step": "owner-approves",
        "keys": [],
        "capture": False,
        "operator_gate": "admission_owner_approval",
        "completion_text": ["Machine connected."],
        "gate_timeout_seconds": 600.0,
    }
    result = execute_linux_recipe(
        _linux(monkeypatch, events),
        entry_surface="yoke setup",
        required_completion="owner-approves",
        config=config,
        size=(120, 40),
    )
    assert result.ok, result.evidence
    runs = [value for kind, value in events if kind == "run"]
    assert runs == [
        "YOKE_MACHINE_HOME=/tmp/yoke-machine-qa-fixtures/machine-admission/"
        "self-hosted/approver /home/qa/.local/bin/yoke machines approve K7F2"
    ]
    step = result.evidence["steps"][0]
    assert step["gate_evidence"]["self_approving"] is True
    assert step["gate_evidence"]["code"] == "K7F2"
