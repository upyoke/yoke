"""Renderer-contract tests for typed ``additionalContext`` delivery via the runner.

These tests fail on the pre-fix tree (the renderer had no allow-with-context
envelope, so typed hint decisions reached telemetry but never produced
model-visible output) and pass once both renderers learn to emit the
``hookSpecificOutput.additionalContext`` envelope on non-deny chains.

Coverage map:

* AC-1 — Typed decision carrying ``audit_fields["additionalContext"]`` reaches
  model-visible output under ``run_event`` for both Claude and Codex.
* AC-5 — Mixed deny+context: deny envelope wins; advisory text never
  replaces the deny narrative.
* AC-9 — Subprocess hook stdout still passes through unchanged when typed
  ``additionalContext`` decisions are also present in the chain.

End-to-end coverage for the three real hint modules
lives in the sibling ``test_hook_runner_additional_context_hints.py``.
Isolated renderer unit coverage lives in
``test_hook_runner_decision_render.py``.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Iterable

import pytest

from runtime.harness.hook_runner import runner as runner_module
from runtime.harness.hook_runner import subprocess_policy
from runtime.harness.hook_runner.adapter_capability import AdapterCapability
from runtime.harness.hook_runner.decision_render import (
    HOOK_SPECIFIC_OUTPUT_KEY,
    render_claude_decision,
    render_codex_decision,
)
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome


def _silence_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "emit_hook_execution_failed",
        "emit_hook_guardrail_evaluated",
        "emit_hook_dispatch_telemetry",
    ):
        monkeypatch.setattr(runner_module._telemetry, name, lambda **k: None)


def _capability(
    monkeypatch: pytest.MonkeyPatch,
    *,
    family: str,
    chain: Iterable[str],
    subprocess_modules: frozenset[str] = frozenset(),
) -> AdapterCapability:
    monkeypatch.setattr(runner_module, "chain_for", lambda *a, **k: list(chain))
    renderer = render_claude_decision if family == "claude" else render_codex_decision
    return AdapterCapability(
        family=family,
        events=frozenset({"PreToolUse", "PostToolUse", "apply_patch"}),
        payload_parser=lambda raw: json.loads(raw) if raw else {},
        decision_renderer=renderer,
        subprocess_modules=subprocess_modules,
    )


def _patch_typed_modules(
    monkeypatch: pytest.MonkeyPatch, mapping: dict[str, Any],
) -> None:
    import importlib

    real_import = importlib.import_module

    def fake_import(name: str) -> Any:
        if name in mapping:
            return mapping[name]
        return real_import(name)

    monkeypatch.setattr(importlib, "import_module", fake_import)


def _typed_decision_module(decision: HookDecision):
    class _Module:
        @staticmethod
        def evaluate(context: HookContext) -> HookDecision:  # noqa: ARG004
            return decision

    return _Module


# ---------------------------------------------------------------------------
# Typed additionalContext reaches model-visible output for both harnesses.
# ---------------------------------------------------------------------------


def test_claude_runner_forwards_typed_additional_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typed NOOP decision carrying ``additionalContext`` reaches Claude output."""
    advisory = "<system-reminder>field-note footer here</system-reminder>"
    decision = HookDecision(
        outcome=Outcome.NOOP,
        audit_fields={"additionalContext": advisory},
        next=Next.CONTINUE,
    )
    _patch_typed_modules(monkeypatch, {"hint.test": _typed_decision_module(decision)})
    capability = _capability(monkeypatch, family="claude", chain=["hint.test"])
    _silence_telemetry(monkeypatch)

    text, exit_code = runner_module.run_event(
        "PostToolUse", capability=capability, stdin_data="",
    )

    assert exit_code == 0
    assert text, "Claude additionalContext envelope must reach stdout"
    payload = json.loads(text)
    hook = payload["hookSpecificOutput"]
    assert hook["hookEventName"] == "PostToolUse"
    assert hook["additionalContext"] == advisory


def test_codex_runner_forwards_typed_additional_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typed NOOP decision carrying ``additionalContext`` reaches Codex output."""
    advisory = "<system-reminder>monitor relay reminder</system-reminder>"
    decision = HookDecision(
        outcome=Outcome.NOOP,
        audit_fields={"additionalContext": advisory},
        next=Next.CONTINUE,
    )
    _patch_typed_modules(monkeypatch, {"hint.test": _typed_decision_module(decision)})
    capability = _capability(monkeypatch, family="codex", chain=["hint.test"])
    _silence_telemetry(monkeypatch)

    text, exit_code = runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data="",
    )

    assert exit_code == 0
    payload = json.loads(text)
    hook = payload["hookSpecificOutput"]
    assert hook["hookEventName"] == "PreToolUse"
    assert hook["additionalContext"] == advisory


def test_multiple_typed_additional_contexts_are_joined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two non-deny decisions with additionalContext join under one envelope."""
    first = HookDecision(
        outcome=Outcome.NOOP,
        audit_fields={"additionalContext": "first reminder"},
        next=Next.CONTINUE,
    )
    second = HookDecision(
        outcome=Outcome.NOOP,
        audit_fields={"additionalContext": "second reminder"},
        next=Next.CONTINUE,
    )
    _patch_typed_modules(monkeypatch, {
        "hint.first": _typed_decision_module(first),
        "hint.second": _typed_decision_module(second),
    })
    capability = _capability(
        monkeypatch, family="claude", chain=["hint.first", "hint.second"],
    )
    _silence_telemetry(monkeypatch)

    text, _ = runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data="",
    )
    payload = json.loads(text)
    ctx = payload["hookSpecificOutput"]["additionalContext"]
    assert "first reminder" in ctx
    assert "second reminder" in ctx


# ---------------------------------------------------------------------------
# Mixed deny+context -- deny wins; advisory text never replaces deny.
# ---------------------------------------------------------------------------


def test_claude_mixed_deny_and_context_preserves_deny(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a deny exists, Claude keeps exit-2 deny narrative; advisory is dropped."""
    deny = HookDecision(
        outcome=Outcome.DENY,
        message="blocked by lint_destructive_git",
        block=True,
    )
    advisory = HookDecision(
        outcome=Outcome.NOOP,
        audit_fields={"additionalContext": "advisory should not replace deny"},
    )
    _patch_typed_modules(monkeypatch, {
        "deny.mod": _typed_decision_module(deny),
        "hint.mod": _typed_decision_module(advisory),
    })
    capability = _capability(
        monkeypatch, family="claude", chain=["deny.mod", "hint.mod"],
    )
    _silence_telemetry(monkeypatch)

    text, exit_code = runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data="",
    )

    assert exit_code == 2, "deny must keep its exit code"
    assert "blocked by lint_destructive_git" in text
    assert "advisory should not replace deny" not in text


def test_codex_mixed_deny_and_context_preserves_deny(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a deny exists, Codex keeps deny envelope; advisory is dropped."""
    deny = HookDecision(
        outcome=Outcome.DENY,
        message="blocked by path_claim_pre_edit_guard",
        block=True,
    )
    advisory = HookDecision(
        outcome=Outcome.NOOP,
        audit_fields={"additionalContext": "advisory should not replace deny"},
    )
    _patch_typed_modules(monkeypatch, {
        "deny.mod": _typed_decision_module(deny),
        "hint.mod": _typed_decision_module(advisory),
    })
    capability = _capability(
        monkeypatch, family="codex", chain=["deny.mod", "hint.mod"],
    )
    _silence_telemetry(monkeypatch)

    text, exit_code = runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data="",
    )

    assert exit_code == 0
    payload = json.loads(text)
    hook = payload[HOOK_SPECIFIC_OUTPUT_KEY]
    assert hook["permissionDecision"] == "deny"
    assert "blocked by path_claim_pre_edit_guard" in hook["permissionDecisionReason"]
    assert "additionalContext" not in hook


# ---------------------------------------------------------------------------
# Subprocess hook stdout passes through alongside typed additionalContext.
# ---------------------------------------------------------------------------


def test_subprocess_stdout_passes_through_with_typed_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-9: subprocess output is appended even when a typed hint also fires."""
    typed_decision = HookDecision(
        outcome=Outcome.NOOP,
        audit_fields={"additionalContext": "typed advisory"},
        next=Next.CONTINUE,
    )
    _patch_typed_modules(
        monkeypatch, {"hint.typed": _typed_decision_module(typed_decision)},
    )
    capability = _capability(
        monkeypatch, family="claude",
        chain=["mod.subproc", "hint.typed"],
        subprocess_modules=frozenset({"mod.subproc"}),
    )

    def fake_run(argv, **kwargs):  # noqa: ARG001
        return subprocess.CompletedProcess(
            args=argv, returncode=0,
            stdout="orientation\nbanner\n", stderr="",
        )

    monkeypatch.setattr(subprocess_policy.subprocess, "run", fake_run)
    _silence_telemetry(monkeypatch)

    text, exit_code = runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data="",
    )

    assert exit_code == 0
    assert "orientation" in text
    assert "banner" in text
    assert "typed advisory" in text


def test_audit_stdout_field_still_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-9: ``audit_fields["stdout"]`` continues to land on stdout verbatim."""
    decision = HookDecision(
        outcome=Outcome.AUDIT_ONLY,
        audit_fields={"stdout": "orientation block\n"},
    )
    _patch_typed_modules(
        monkeypatch, {"mod.lifecycle": _typed_decision_module(decision)},
    )
    capability = _capability(
        monkeypatch, family="claude", chain=["mod.lifecycle"],
    )
    _silence_telemetry(monkeypatch)

    text, exit_code = runner_module.run_event(
        "SessionStart", capability=capability, stdin_data="",
    )
    assert exit_code == 0
    assert "orientation block" in text
