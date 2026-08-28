"""Reinjection proof for the first Fleet acceptance receipt."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.tools.session_control_live_acceptance_contract import (
    ACCEPTANCE_SURFACES,
    AcceptanceCell,
    AcceptanceContractError,
)
from runtime.api.tools.session_control_live_acceptance_protocol import (
    RECEIPT_ONLY_PROTOCOL,
    initial_delivery_message,
    wake_delivery_message,
)
from runtime.api.tools.test_session_control_live_acceptance_driver import (
    _ScenarioClient,
    _driver,
)
from yoke_contracts.session_control.capabilities import capability_for_surface


class _MissingInjectionAckClient(_ScenarioClient):
    def simulate_target_tool_hook(self) -> None:
        self.message_states["initial-message"] = (True, 0)
        self.tool_hook_events.append("initial-message")


class _ExtraProbeInjectionClient(_ScenarioClient):
    def simulate_target_tool_hook(self) -> None:
        super().simulate_target_tool_hook()
        message_id = self.tool_hook_events[-1]
        self.message_states[message_id] = (True, 3)


def test_all_acceptance_surfaces_retain_reinjection_hook_coverage() -> None:
    for surface in ACCEPTANCE_SURFACES:
        capability = capability_for_surface(surface)
        assert capability is not None
        assert "PostToolUse" in capability.inject_events

    root = Path(__file__).resolve().parents[3]
    claude = json.loads((root / ".claude/settings.json").read_text(encoding="utf-8"))
    codex = json.loads((root / ".codex/hooks.json").read_text(encoding="utf-8"))
    cursor = json.loads((root / ".cursor/hooks.json").read_text(encoding="utf-8"))
    for config in (claude, codex):
        post = config["hooks"]["PostToolUse"]
        assert any(entry.get("matcher") == "Bash" for entry in post)
    assert "Stop" in codex["hooks"]
    for surface in ("codex-cli", "codex-desktop", "codex-vscode"):
        assert "Stop" not in capability_for_surface(surface).inject_events
    after_shell = cursor["hooks"]["afterShellExecution"]
    assert any("evaluate PostToolUse" in entry["command"] for entry in after_shell)


def test_fake_receipt_reads_do_not_simulate_target_hooks() -> None:
    cell = AcceptanceCell("codex-cli", "0.149.0-alpha.4", "identify")
    client = _ScenarioClient(cell)
    client.message_states["initial-message"] = (False, 1)

    first = client._message("initial-message")
    second = client._message("initial-message")

    assert first == second
    assert first["message"]["recipients"][0]["injection_count"] == 1
    assert client.tool_hook_events == []


def test_live_create_launch_message_accepts_first_injection_ack() -> None:
    cell = AcceptanceCell("claude-cli", "2.1.241", "create", wake_route="direct")
    client = _ScenarioClient(cell)

    report = _driver(client)._run_cell(
        "yoke",
        cell,
        run_id="launch-reinjection-proof",
        timeout=10,
        poll=1,
        unsupported_observation=2,
    )

    assert report["status"] == "passed"
    assert client.message_reads["launch-message"] == 2
    assert client.tool_hook_events == ["launch-message"]
    assert report["initial_message"]["injection_count"] == 1
    bodies = [body for argv, body in client.calls if argv[:2] == ["sessions", "create"]]
    assert bodies[-1] == initial_delivery_message(
        surface=cell.surface,
        phase="launch",
    )
    assert RECEIPT_ONLY_PROTOCOL in bodies[-1]
    assert "do not acknowledge" not in bodies[-1]


def test_live_initial_delivery_accepts_first_injection_ack() -> None:
    cell = AcceptanceCell(
        "codex-cli",
        "0.149.0-alpha.4",
        "identify",
        session_id="reinjection-target",
    )
    client = _ScenarioClient(cell)

    report = _driver(client)._run_cell(
        "yoke",
        cell,
        run_id="reinjection-proof",
        timeout=10,
        poll=1,
        unsupported_observation=2,
    )

    assert report["status"] == "passed"
    assert client.message_reads["initial-message"] == 2
    assert client.tool_hook_events == ["initial-message"]
    assert report["initial_message"]["injection_count"] == 1
    assert report["wake_message"]["injection_count"] == 1
    bodies = [body for argv, body in client.calls if argv[:2] == ["say", "--stdin"]]
    assert bodies[0] == initial_delivery_message(
        surface=cell.surface,
        phase="initial delivery",
    )
    assert bodies[-1] == wake_delivery_message(
        surface=cell.surface,
        phase="stopped-session wake",
    )

    extra_report = _driver(_ExtraProbeInjectionClient(cell))._run_cell(
        "yoke",
        cell,
        run_id="extra-probe-injection",
        timeout=10,
        poll=1,
        unsupported_observation=2,
    )
    assert extra_report["initial_message"]["injection_count"] == 3

    with pytest.raises(AcceptanceContractError) as captured:
        _driver(_MissingInjectionAckClient(cell))._run_cell(
            "yoke",
            cell,
            run_id="missing-injection-ack",
            timeout=10,
            poll=1,
            unsupported_observation=2,
        )
    assert captured.value.code == "ack_evidence_invalid"
