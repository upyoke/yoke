"""Human hook attribution never changes structured delivery contracts."""

from __future__ import annotations

import json
import subprocess

import pytest

from yoke_contracts.hook_diagnostics import format_hook_diagnostic
from yoke_contracts.hook_inline_context import inline_context_bytes_for_harness
from yoke_contracts.hook_context_compose import token_delivered
from yoke_core.hooks.decision_render import (
    render_claude_decision,
    render_codex_decision,
    render_cursor_decision,
)
from yoke_core.hooks.types import HookDecision, Outcome
from yoke_harness.hooks.decision_render import merge_allow_stdout, write_hook_output
from yoke_harness.git_hooks import pre_commit
from yoke_cli.project_snapshot import identity_sync_payload, plan_sync


def test_labels_preserve_multiline_recovery_and_do_not_repeat():
    body = "WARNING: staged change\n  app.py\nRun git add app.py.\n"
    labeled = format_hook_diagnostic("pre-commit", body)
    assert labeled == "yoke (pre-commit): " + body
    assert format_hook_diagnostic("pre-commit", labeled) == labeled
    assert format_hook_diagnostic("pre-commit", "") == ""


def test_successful_pre_commit_is_silent(monkeypatch, capsys):
    monkeypatch.setattr(pre_commit, "_git_name_only", lambda args: [])
    monkeypatch.setattr(pre_commit, "_resolve_repo_root", lambda: None)
    assert pre_commit.run() == 0
    assert capsys.readouterr() == ("", "")


def test_diverged_staging_warning_is_labeled_and_actionable(monkeypatch, capsys):
    monkeypatch.setattr(pre_commit, "_git_name_only", lambda args: ["app.py"])
    monkeypatch.setattr(pre_commit, "_resolve_repo_root", lambda: None)
    assert pre_commit.run() == 0
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err.startswith("yoke (pre-commit): WARNING:")
    assert "git add <file>" in out.err


def test_identity_only_scan_is_silent_and_preserves_head(tmp_path, capsys):
    def git(*args):
        return subprocess.run(
            ["git", "-C", str(tmp_path), *args],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    git("-c", "core.hooksPath=/dev/null", "commit", "--allow-empty", "-m", "initial")
    plan = plan_sync(tmp_path, integration_target=None, head_only=True)
    payload = identity_sync_payload(plan, project_id="demo", hook_mode=True)
    assert payload.snapshots[0].commit_sha == git("rev-parse", "HEAD")
    assert not payload.snapshots[0].contents_included
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    "harness,render",
    [
        ("claude-code", render_claude_decision),
        ("codex", render_codex_decision),
        ("cursor", render_cursor_decision),
    ],
)
def test_actual_combined_wire_delivery_preserves_required_context(
    harness, render, capsys
):
    token = "YOKE_SESSION_MESSAGE_LEASE:diagnostics"
    message_id = "11111111-2222-4333-8444-555555555555"
    delivery = (
        f"=== BEGIN YOKE SESSION MESSAGE DELIVERY {token} {message_id} ===\n"
        '| "Read the mandate and acknowledge it."\n'
        "=== END YOKE SESSION MESSAGE DELIVERY ==="
    )
    required = (
        "Yoke Orientation\nSession: machine-session\n"
        "Instruction: hold the claim.\nContinuation: resume the same handle.\n"
        "Handoff: read the next skill.\nRecovery: yoke messages get " + message_id
    )
    # Both halves pass through the real wire composer, then the final sink.
    context = delivery + "\n\n" + required
    first, code = render(
        [HookDecision(Outcome.AUDIT_ONLY, audit_fields={"additionalContext": context})],
        "PostToolUse",
    )
    second, _ = render(
        [
            HookDecision(
                Outcome.NOOP, audit_fields={"additionalContext": "optional " * 2000}
            )
        ],
        "PostToolUse",
    )
    combined = merge_allow_stdout(first, second, "PostToolUse", harness_id=harness)
    write_hook_output(combined, code, harness, event_name="PostToolUse")
    out = capsys.readouterr()
    payload = json.loads(out.out)
    body = (
        payload["additional_context"]
        if harness == "cursor"
        else payload["hookSpecificOutput"]["additionalContext"]
    )
    assert len(body.encode()) <= inline_context_bytes_for_harness(harness)
    assert delivery in body
    assert required in body
    assert token_delivered(out.out, token)
    assert not out.out.startswith("yoke (")
    assert out.err == ""


@pytest.mark.parametrize("harness", ["codex", "cursor"])
def test_machine_json_is_byte_identical_at_output(harness, capsys):
    text = json.dumps({"machine_id": "unchanged", "permission": "allow"})
    write_hook_output(text, 0, harness, event_name="PreToolUse")
    assert capsys.readouterr() == (text, "")


def test_cursor_degradation_keeps_recovery_and_delivery_under_budget(
    monkeypatch, capsys
):
    from yoke_harness.hooks import relay_degrade

    monkeypatch.setattr(relay_degrade, "detect_executor", lambda: "cursor")
    token = "YOKE_SESSION_MESSAGE_LEASE:diagnostics"
    message_id = "11111111-2222-4333-8444-555555555555"
    delivery = (
        f"=== BEGIN YOKE SESSION MESSAGE DELIVERY {token} {message_id} ===\n"
        '| "' + "mandate " * 2000 + '"\n'
        "=== END YOKE SESSION MESSAGE DELIVERY ==="
    )
    preserved = json.dumps({"additional_context": delivery})
    assert (
        relay_degrade.degrade_to_noop(
            "PostToolUse", "connection unavailable", preserved_stdout=preserved
        )
        == 0
    )
    out = capsys.readouterr()
    body = json.loads(out.out)["additional_context"]
    assert len(body.encode()) <= inline_context_bytes_for_harness("cursor")
    assert body.startswith("WARNING: Yoke guard rules are NOT being enforced")
    assert "connection unavailable" in body
    assert token_delivered(out.out, token)
    assert "yoke messages get " + message_id in body
    assert "yoke messages acknowledge " + message_id in body
