"""Claude blocking output is visible across local and relayed evaluation."""

from __future__ import annotations

import pytest

from yoke_harness.hooks.decision_render import write_hook_output
from yoke_harness.hooks.guard_version_skew import annotate_guard_version_skew
from yoke_harness.hooks.local_policies import deny_stdout


@pytest.mark.parametrize("executor", ["claude", "claude-code", "claude-desktop"])
@pytest.mark.parametrize("ending", ["", "\n"])
def test_claude_local_envelope_emits_reason_on_stderr(executor, ending, capsys) -> None:
    text, exit_code = deny_stdout(
        f"BLOCKED: reason and recovery{ending}", "PreToolUse", executor
    )

    write_hook_output(text, exit_code, executor)

    output = capsys.readouterr()
    assert exit_code == 2
    assert output.err == "BLOCKED: reason and recovery\n"
    assert output.out == ""


@pytest.mark.parametrize("executor", ["codex", "cursor"])
def test_other_harness_denial_envelopes_stay_on_stdout(executor, capsys) -> None:
    text, exit_code = deny_stdout("BLOCKED: reason", "PreToolUse", executor)

    write_hook_output(text, exit_code, executor)

    output = capsys.readouterr()
    assert exit_code == 0
    assert output.out == text
    assert output.err == ""


def test_relayed_denial_preserves_version_notice_on_stderr(capsys) -> None:
    text = annotate_guard_version_skew(
        "BLOCKED: reason and recovery",
        client={"source_sha": "a" * 40},
        server={"source_sha": "b" * 40},
    )

    write_hook_output(text, 2, "claude-code")

    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == f"{text}\n"
    assert "server revision" in output.err


def test_claude_allow_context_stays_on_stdout(capsys) -> None:
    write_hook_output("allow context", 0, "claude-code")

    output = capsys.readouterr()
    assert output.out == "allow context"
    assert output.err == ""
