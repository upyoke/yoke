"""Tests for yoke_core.domain.hint_monitor_relay."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

import pytest

from yoke_core.domain import hint_monitor_relay
from runtime.harness.hook_runner.types import HookContext, Outcome


def _make_context(payload_dict: dict) -> HookContext:
    tool = payload_dict.get("tool_name")
    return HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload_dict,
        tool_name=tool if isinstance(tool, str) else None,
    )


def _captured_run(payload: str) -> str:
    """Mirror the legacy stdin -> stdout path via the typed evaluate()."""
    if not payload or not payload.strip():
        return ""
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, dict):
        return ""
    decision = hint_monitor_relay.evaluate(_make_context(parsed))
    additional = decision.audit_fields.get("additionalContext")
    if not additional:
        return ""
    return json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": additional,
        }
    })


def _write_machine_config(tmp_path, monkeypatch, value: str) -> None:
    config_path = tmp_path / ".yoke" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps({"settings": {hint_monitor_relay.CONFIG_KEY: value}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(config_path))


def test_monitor_payload_emits_pretooluse_hookspecificoutput() -> None:
    payload = json.dumps(
        {
            "tool_name": "Monitor",
            "tool_input": {"command": "tail -f /tmp/x.log"},
        }
    )
    raw = _captured_run(payload)
    assert raw, "expected hookSpecificOutput on a valid Monitor payload"
    out = json.loads(raw)
    assert "hookSpecificOutput" in out
    inner = out["hookSpecificOutput"]
    assert inner["hookEventName"] == "PreToolUse"
    assert isinstance(inner["additionalContext"], str)
    assert inner["additionalContext"].strip(), "additionalContext must be non-empty"


def test_default_reminder_anchored_on_observed_failure_modes() -> None:
    text = hint_monitor_relay.DEFAULT_REMINDER
    assert "tail" in text.lower(), "must warn against capture-file peeks"
    assert "filler" in text.lower(), "must warn against filler text between wakes"
    assert "matched line" in text.lower(), "must anchor on the relay-the-matched-line rule"


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "   ",
        "\n\n",
        "not json at all",
        "{not: valid}",
        "[1,2,3]",
    ],
)
def test_malformed_or_empty_stdin_exits_silently(payload: str) -> None:
    assert _captured_run(payload) == ""


@pytest.mark.parametrize(
    "tool_name",
    ["Bash", "Edit", "Write", "ScheduleWakeup", "TaskOutput", ""],
)
def test_non_monitor_tool_emits_nothing(tool_name: str) -> None:
    payload = json.dumps({"tool_name": tool_name, "tool_input": {}})
    assert _captured_run(payload) == ""


def test_main_returns_zero_on_empty_stdin(monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = hint_monitor_relay.main()
    assert rc == 0
    assert buf.getvalue() == ""


def test_config_override_replaces_default_reminder(tmp_path, monkeypatch) -> None:
    _write_machine_config(tmp_path, monkeypatch, "custom relay reminder")
    text = hint_monitor_relay.resolve_reminder_text()
    assert text == "custom relay reminder"
    assert text != hint_monitor_relay.DEFAULT_REMINDER


def test_blank_config_override_falls_back_to_default(tmp_path, monkeypatch) -> None:
    _write_machine_config(tmp_path, monkeypatch, "   ")
    assert hint_monitor_relay.resolve_reminder_text() == hint_monitor_relay.DEFAULT_REMINDER


def test_missing_config_falls_back_to_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("YOKE_TARGET_REPO_ROOT", str(tmp_path))
    monkeypatch.delenv("YOKE_REPO_ROOT", raising=False)
    assert hint_monitor_relay.resolve_reminder_text() == hint_monitor_relay.DEFAULT_REMINDER


def test_run_uses_resolved_text_for_monitor_payload(tmp_path, monkeypatch) -> None:
    _write_machine_config(tmp_path, monkeypatch, "alt-reminder-XYZ")
    payload = json.dumps({"tool_name": "Monitor", "tool_input": {}})
    raw = _captured_run(payload)
    out = json.loads(raw)
    assert out["hookSpecificOutput"]["additionalContext"] == "alt-reminder-XYZ"


def test_evaluate_typed_returns_noop_with_additional_context() -> None:
    record = _make_context({"tool_name": "Monitor", "tool_input": {}})
    decision = hint_monitor_relay.evaluate(record)
    assert decision.outcome is Outcome.NOOP
    assert decision.block is False
    assert decision.audit_fields.get("additionalContext", "").strip()


def test_evaluate_typed_skips_non_monitor_tool() -> None:
    record = _make_context({"tool_name": "Bash", "tool_input": {}})
    decision = hint_monitor_relay.evaluate(record)
    assert decision.outcome is Outcome.NOOP
    assert decision.audit_fields == {}
