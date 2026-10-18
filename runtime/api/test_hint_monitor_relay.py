"""Tests for yoke_core.domain.hint_monitor_relay."""

from __future__ import annotations

from runtime.api.fixtures.machine_config_test import select_machine_config_file
import io
import subprocess
import unittest
from pathlib import Path
import json
from contextlib import redirect_stdout

import pytest

from yoke_contracts.hook_runner.client_facts import MACHINE_SETTINGS_KEY, client_fact
from yoke_core.domain import hint_monitor_relay
from yoke_core.domain.hint_monitor_relay import (
    DEFAULT_REMINDER,
    HELP_REMINDER,
    main,
    resolve_reminder_text,
)
from yoke_core.hooks.types import HookContext, Outcome


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
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": additional,
            }
        }
    )


def _write_machine_config(tmp_path, monkeypatch, value: str) -> None:
    config_path = tmp_path / ".yoke" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps({"settings": {hint_monitor_relay.CONFIG_KEY: value}}) + "\n",
        encoding="utf-8",
    )
    select_machine_config_file(monkeypatch, config_path)


def _settings_fact(value: str) -> dict:
    """The client's machine-settings fact carrying one reminder override."""
    return client_fact(MACHINE_SETTINGS_KEY, {hint_monitor_relay.CONFIG_KEY: value})


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
    text = hint_monitor_relay.HELP_REMINDER
    assert "tail" in text.lower(), "must warn against capture-file peeks"
    assert "filler" in text.lower(), "must warn against filler text between wakes"
    assert "matched line" in text.lower(), (
        "must anchor on the relay-the-matched-line rule"
    )
    injected = hint_monitor_relay.DEFAULT_REMINDER
    injected_words = " ".join(injected.split())
    assert "SUBSCRIPTION" in injected
    assert "hint_monitor_relay --help" in injected
    assert "something it would act on" in injected_words
    assert "Ending a turn sends no" in injected_words
    assert "yoke say --steering" in injected_words
    assert "Message another session only" in hint_monitor_relay.HELP_REMINDER


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


def test_client_setting_replaces_default_reminder() -> None:
    text = hint_monitor_relay.resolve_reminder_text(
        _settings_fact("custom relay reminder")
    )
    assert text == "custom relay reminder"
    assert text != hint_monitor_relay.DEFAULT_REMINDER


def test_blank_client_setting_falls_back_to_default() -> None:
    assert (
        hint_monitor_relay.resolve_reminder_text(_settings_fact("   "))
        == hint_monitor_relay.DEFAULT_REMINDER
    )


def test_missing_client_fact_falls_back_to_default() -> None:
    assert (
        hint_monitor_relay.resolve_reminder_text({})
        == hint_monitor_relay.DEFAULT_REMINDER
    )


def test_server_machine_config_is_never_read(tmp_path, monkeypatch) -> None:
    """Only the client's fact carries the override; the evaluator's own
    machine config does not."""
    _write_machine_config(tmp_path, monkeypatch, "evaluator-local-text")
    assert (
        hint_monitor_relay.resolve_reminder_text({})
        == hint_monitor_relay.DEFAULT_REMINDER
    )


def test_run_uses_resolved_text_for_monitor_payload() -> None:
    payload = json.dumps(
        {"tool_name": "Monitor", "tool_input": {}, **_settings_fact("alt-reminder-XYZ")}
    )
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


REMINDER_REPO_ROOT = Path(__file__).resolve().parents[2]
REMINDER_SOURCE_ROOT = REMINDER_REPO_ROOT / "packages" / "yoke-core" / "src"


class TestDefaultReminderContent(unittest.TestCase):
    """The widened reminder mirrors the deny-side coverage."""

    def test_widened_peek_verb_enumeration_present(self) -> None:
        self.assertIn(
            "tail/head/cat/wc/grep/egrep/fgrep/rg/ls/awk/sed/less/more/file/stat/nl/cut/sort/uniq",
            HELP_REMINDER,
        )

    def test_legacy_three_verb_phrasing_replaced(self) -> None:
        # The old "(tail/head/cat) while the owning command is
        # running" wording must be removed (replacement, not addition).
        text = HELP_REMINDER
        self.assertNotIn(
            "(tail/head/cat) while the owning command is running",
            text,
        )

    def test_bg_waiter_prohibition_present(self) -> None:
        # The four waiter shapes are named.
        text = HELP_REMINDER
        self.assertIn("Bash(run_in_background)", text)
        self.assertIn("tail -f <capture>", text)
        self.assertIn("sleep N && tail/cat <capture>", text)
        self.assertIn("while [ ! -f <sentinel> ]; do sleep; done", text)
        self.assertIn("watch_tail <capture>", text)
        self.assertIn("armed Monitor IS the waiter", text)

    def test_private_tmp_claude_path_called_out(self) -> None:
        # The Claude private-tmp capture root is named explicitly.
        text = HELP_REMINDER
        self.assertIn("/private/tmp/claude-", text)
        # And the prose links it to the existing peek/waiter rules.
        self.assertIn("peek", text)
        self.assertIn("waiter", text)
        self.assertNotIn("pgrep -f <pattern>", text)

    def test_envelope_shape_preserved(self) -> None:
        # The reminder is wrapped in exactly one envelope.
        text = HELP_REMINDER
        self.assertTrue(text.startswith("<system-reminder>"))
        self.assertTrue(text.rstrip().endswith("</system-reminder>"))
        # No nested envelopes.
        self.assertEqual(text.count("<system-reminder>"), 1)
        self.assertEqual(text.count("</system-reminder>"), 1)

    def test_turn_end_is_not_the_wait(self) -> None:
        text = HELP_REMINDER
        self.assertNotIn("Waiting IS ending the turn", text)
        self.assertIn("waiter dies with no wake", text)
        self.assertIn("wait_mode=background-wake", text)
        self.assertIn("wait_mode=in-turn", text)
        self.assertNotIn("the completion notification was the verification", text)


class TestReminderModuleSize(unittest.TestCase):
    """hint_monitor_relay.py stays ≤200 lines."""

    def test_module_size_under_cap(self) -> None:
        path = REMINDER_SOURCE_ROOT / "yoke_core" / "domain" / "hint_monitor_relay.py"
        line_count = sum(1 for _ in path.read_text(encoding="utf-8").splitlines())
        self.assertLessEqual(line_count, 200)


class TestReminderSingleSourceOfTruth(unittest.TestCase):
    """``DEFAULT_REMINDER`` is the only canonical reminder source.

    A grep for the ``"Avoid repeated peeks at the capture file"`` substring across
    ``packages/yoke-core/src`` returns exactly one hit (the canonical
    constant in ``hint_monitor_relay.py``).
    """

    def test_only_one_canonical_definition(self) -> None:
        # The substring is an exact match against the widened reminder
        # text. Only the canonical module should carry it. Skip __pycache__
        # (bytecode caches contain the source-literal verbatim) and this
        # test file itself.
        try:
            output = subprocess.run(
                [
                    "grep",
                    "-r",
                    "--exclude-dir=__pycache__",
                    "-l",
                    "--exclude-dir=__pycache__",
                    "Avoid repeated peeks at the capture file",
                    str(REMINDER_SOURCE_ROOT),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            self.skipTest("grep not available on this platform")
        if output.returncode not in (0, 1):
            self.fail(f"grep failed: rc={output.returncode} stderr={output.stderr}")
        hits = [line.strip() for line in output.stdout.splitlines() if line.strip()]
        hits = [h for h in hits if not h.endswith("test_hint_monitor_relay.py")]
        self.assertEqual(len(hits), 1, f"expected 1 hit, got: {hits}")
        self.assertTrue(hits[0].endswith("hint_monitor_relay_help.py"))


class TestDefaultReminderConstantParity(unittest.TestCase):
    """``DEFAULT_REMINDER`` and ``resolve_reminder_text({})`` agree without override."""

    def test_default_resolves_when_no_override(self) -> None:
        text = resolve_reminder_text({})
        self.assertTrue(
            text == DEFAULT_REMINDER or text.strip() == DEFAULT_REMINDER.strip()
        )


class TestInjectedReminderIsShort(unittest.TestCase):
    """The hook injects a few lines; full rules live on ``--help``."""

    def test_injected_text_points_at_help(self) -> None:
        self.assertIn(
            "python3 -m yoke_core.domain.hint_monitor_relay --help", DEFAULT_REMINDER
        )
        self.assertLessEqual(DEFAULT_REMINDER.count("\n"), 12)
        self.assertTrue(DEFAULT_REMINDER.startswith("<system-reminder>"))

    def test_help_prints_the_full_relay_rules(self) -> None:
        from io import StringIO
        from contextlib import redirect_stdout

        buf = StringIO()
        with redirect_stdout(buf):
            rc = main(["--help"])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().rstrip(), HELP_REMINDER.rstrip())


if __name__ == "__main__":
    unittest.main()
