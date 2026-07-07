"""Tests for ``runtime.harness.hook_runner.decision_render``.

Covers AC-T4 (Claude empty-decision case is ``("", 0)``), AC-T5 (Codex
empty-decision case is the apply-patch deny envelope shape), plus the
deny narrative aggregation behavior every chain-eligible policy module
will rely on.
"""

from __future__ import annotations

import json

from runtime.harness.hook_runner.decision_render import (
    HOOK_SPECIFIC_OUTPUT_KEY,
    merge_allow_stdout,
    render_claude_decision,
    render_codex_decision,
)
from runtime.harness.hook_runner.types import HookDecision, Outcome


def _allow() -> HookDecision:
    return HookDecision(outcome=Outcome.ALLOW)


def _deny(message: str) -> HookDecision:
    return HookDecision(outcome=Outcome.DENY, message=message, block=True)


def _audit(message: str = "logged") -> HookDecision:
    return HookDecision(outcome=Outcome.AUDIT_ONLY, message=message)


def _suppression(message: str = "suppression token recorded") -> HookDecision:
    return HookDecision(outcome=Outcome.SUPPRESSION_ATTEMPTED, message=message)


def _advisory(text: str) -> HookDecision:
    return HookDecision(
        outcome=Outcome.NOOP,
        audit_fields={"additionalContext": text},
    )


def test_claude_empty_decisions_returns_allow_pair() -> None:
    """AC-T4: empty decisions return ``("", 0)``."""
    assert render_claude_decision([], "PreToolUse") == ("", 0)


def test_claude_no_deny_decisions_returns_allow_pair() -> None:
    """Allow / audit / suppression-only decisions also yield empty allow."""
    assert render_claude_decision(
        [_allow(), _audit(), _suppression()],
        "PreToolUse",
    ) == ("", 0)


def test_claude_single_deny_decision_renders_narrative_and_exit_two() -> None:
    """A single deny decision renders the narrative on stdout, exit 2."""
    stdout, code = render_claude_decision(
        [_deny("blocked by lint_main_commit")],
        "PreToolUse",
    )
    assert code == 2
    assert "blocked by lint_main_commit" in stdout


def test_claude_multiple_deny_decisions_concatenate_narratives() -> None:
    """Multiple deny decisions join their narratives in chain order."""
    stdout, code = render_claude_decision(
        [_deny("first deny"), _allow(), _deny("second deny")],
        "PreToolUse",
    )
    assert code == 2
    assert "first deny" in stdout
    assert "second deny" in stdout


def test_codex_empty_decisions_returns_allow_pair() -> None:
    """AC-T5: empty decisions return the Codex apply-patch allow shape.

    The Codex wire format treats absence of a ``hookSpecificOutput`` deny
    envelope as allow; we render that as ``("", 0)`` to match today's
    ``codex_hooks_tool_events._extract_pre_tool_deny_json`` no-deny path.
    """
    assert render_codex_decision([], "PreToolUse") == ("", 0)


def test_codex_no_deny_decisions_returns_allow_pair() -> None:
    """Non-deny decisions also produce empty allow on the Codex side."""
    assert render_codex_decision(
        [_allow(), _audit(), _suppression()],
        "apply_patch",
    ) == ("", 0)


def test_codex_single_deny_renders_pre_tool_use_envelope() -> None:
    """A deny decision renders the ``hookSpecificOutput`` JSON envelope."""
    stdout, code = render_codex_decision(
        [_deny("blocked by path_claim_pre_edit_guard")],
        "PreToolUse",
    )
    assert code == 0
    payload = json.loads(stdout)
    hook = payload[HOOK_SPECIFIC_OUTPUT_KEY]
    assert hook["hookEventName"] == "PreToolUse"
    assert hook["permissionDecision"] == "deny"
    assert "path_claim_pre_edit_guard" in hook["permissionDecisionReason"]


def test_codex_apply_patch_event_renders_pre_tool_use_envelope() -> None:
    """``apply_patch`` denies still travel under the PreToolUse envelope."""
    stdout, _code = render_codex_decision(
        [_deny("blocked by lint_session_cwd")],
        "apply_patch",
    )
    payload = json.loads(stdout)
    hook = payload[HOOK_SPECIFIC_OUTPUT_KEY]
    assert hook["hookEventName"] == "PreToolUse"
    assert hook["permissionDecision"] == "deny"


def test_codex_block_only_decision_still_renders_deny() -> None:
    """A decision with ``block=True`` but a non-DENY outcome still denies.

    Some policies set ``block=True`` while keeping the outcome WARN to
    record the warn-mode classification on the audit row. The renderer
    treats either signal as deny so behavior is preserved.
    """
    decision = HookDecision(
        outcome=Outcome.WARN,
        message="warn mode raised to deny by override",
        block=True,
    )
    stdout, code = render_codex_decision([decision], "PreToolUse")
    assert code == 0
    payload = json.loads(stdout)
    hook = payload[HOOK_SPECIFIC_OUTPUT_KEY]
    assert hook["permissionDecision"] == "deny"


def test_claude_block_only_decision_still_renders_deny() -> None:
    """Claude renderer also treats ``block=True`` as deny regardless of outcome."""
    decision = HookDecision(
        outcome=Outcome.WARN,
        message="warn mode raised to deny by override",
        block=True,
    )
    stdout, code = render_claude_decision([decision], "PreToolUse")
    assert code == 2
    assert "warn mode raised to deny by override" in stdout


# ---------------------------------------------------------------------------
# Allow-with-context envelope for non-blocking advisories.
# ---------------------------------------------------------------------------


def test_claude_single_advisory_emits_additional_context_envelope() -> None:
    """AC-3: a single non-deny decision with additionalContext renders the envelope."""
    stdout, code = render_claude_decision(
        [_advisory("<system-reminder>advisory text</system-reminder>")],
        "PostToolUse",
    )
    assert code == 0
    payload = json.loads(stdout)
    hook = payload[HOOK_SPECIFIC_OUTPUT_KEY]
    assert hook["hookEventName"] == "PostToolUse"
    assert hook["additionalContext"] == "<system-reminder>advisory text</system-reminder>"
    assert "permissionDecision" not in hook


def test_codex_single_advisory_emits_additional_context_envelope() -> None:
    """AC-4: Codex emits the same allow-with-context envelope shape."""
    stdout, code = render_codex_decision(
        [_advisory("advisory text")],
        "PreToolUse",
    )
    assert code == 0
    payload = json.loads(stdout)
    hook = payload[HOOK_SPECIFIC_OUTPUT_KEY]
    assert hook["hookEventName"] == "PreToolUse"
    assert hook["additionalContext"] == "advisory text"
    assert "permissionDecision" not in hook


def test_claude_multiple_advisories_join_with_blank_line() -> None:
    """Multiple advisories join with a blank line, in chain order."""
    stdout, _ = render_claude_decision(
        [_advisory("first reminder"), _advisory("second reminder")],
        "PreToolUse",
    )
    payload = json.loads(stdout)
    ctx = payload[HOOK_SPECIFIC_OUTPUT_KEY]["additionalContext"]
    assert ctx == "first reminder\n\nsecond reminder"


def test_codex_multiple_advisories_join_with_blank_line() -> None:
    """Codex multi-advisory join preserves chain order and blank-line separator."""
    stdout, _ = render_codex_decision(
        [_advisory("first reminder"), _advisory("second reminder")],
        "PostToolUse",
    )
    payload = json.loads(stdout)
    ctx = payload[HOOK_SPECIFIC_OUTPUT_KEY]["additionalContext"]
    assert ctx == "first reminder\n\nsecond reminder"


def test_blank_additional_context_is_treated_as_no_advisory() -> None:
    """Empty / whitespace-only ``additionalContext`` does not emit an envelope."""
    stdout_claude, code_claude = render_claude_decision(
        [_advisory("   \n\t  ")], "PreToolUse",
    )
    stdout_codex, code_codex = render_codex_decision(
        [_advisory("")], "PreToolUse",
    )
    assert (stdout_claude, code_claude) == ("", 0)
    assert (stdout_codex, code_codex) == ("", 0)


# ---------------------------------------------------------------------------
# Mixed deny + advisory — deny envelope wins, advisory is dropped.
# ---------------------------------------------------------------------------


def test_claude_mixed_deny_and_advisory_drops_advisory() -> None:
    """AC-5: when a deny exists, the Claude renderer keeps exit-2 narrative
    and drops the advisory so deny text cannot be hidden or replaced."""
    stdout, code = render_claude_decision(
        [_deny("blocked by lint_destructive_git"), _advisory("would-be advisory")],
        "PreToolUse",
    )
    assert code == 2
    assert "blocked by lint_destructive_git" in stdout
    assert "would-be advisory" not in stdout


def test_codex_mixed_deny_and_advisory_drops_advisory() -> None:
    """AC-5: Codex keeps deny envelope and drops the advisory."""
    stdout, code = render_codex_decision(
        [_deny("blocked by path_claim_pre_edit_guard"), _advisory("would-be advisory")],
        "PreToolUse",
    )
    assert code == 0
    payload = json.loads(stdout)
    hook = payload[HOOK_SPECIFIC_OUTPUT_KEY]
    assert hook["permissionDecision"] == "deny"
    assert "blocked by path_claim_pre_edit_guard" in hook["permissionDecisionReason"]
    assert "additionalContext" not in hook
    assert "would-be advisory" not in stdout


def test_codex_apply_patch_deny_with_advisory_still_remaps_event_name() -> None:
    """``apply_patch`` deny+advisory still declares ``PreToolUse`` and drops advisory."""
    stdout, _ = render_codex_decision(
        [_deny("blocked by lint_session_cwd"), _advisory("would-be advisory")],
        "apply_patch",
    )
    payload = json.loads(stdout)
    hook = payload[HOOK_SPECIFIC_OUTPUT_KEY]
    assert hook["hookEventName"] == "PreToolUse"
    assert "additionalContext" not in hook


def _envelope(body: str, event_name: str = "PreToolUse") -> str:
    return json.dumps({
        HOOK_SPECIFIC_OUTPUT_KEY: {
            "hookEventName": event_name,
            "additionalContext": body,
        }
    })


def test_merge_allow_stdout_empty_sides_pass_through() -> None:
    assert merge_allow_stdout("", "x", "PreToolUse") == "x"
    assert merge_allow_stdout("x", "", "PreToolUse") == "x"
    assert merge_allow_stdout("", "", "PreToolUse") == ""


def test_merge_allow_stdout_joins_two_context_envelopes() -> None:
    merged = merge_allow_stdout(
        _envelope("client hint"), _envelope("server hint"), "PreToolUse",
    )
    payload = json.loads(merged)
    hook = payload[HOOK_SPECIFIC_OUTPUT_KEY]
    assert hook["hookEventName"] == "PreToolUse"
    assert hook["additionalContext"] == "client hint\n\nserver hint"


def test_merge_allow_stdout_mixed_shapes_concatenate_raw() -> None:
    # Plain text + envelope: the same raw join run_event itself produces
    # for rendered-envelope + extra subprocess stdout.
    plain = "## Yoke Orientation\n"
    envelope = _envelope("server hint")
    assert merge_allow_stdout(plain, envelope, "PreToolUse") == plain + envelope
    assert merge_allow_stdout(envelope, plain, "PreToolUse") == envelope + plain


def test_merge_allow_stdout_never_treats_deny_envelope_as_context() -> None:
    deny_envelope = json.dumps({
        HOOK_SPECIFIC_OUTPUT_KEY: {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "no",
        }
    })
    merged = merge_allow_stdout(deny_envelope, _envelope("hint"), "PreToolUse")
    # Raw concatenation — the deny envelope text is preserved verbatim,
    # never absorbed into a joined advisory envelope.
    assert merged.startswith(deny_envelope)
