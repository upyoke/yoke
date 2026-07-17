"""Tests for the central enforcement-mode gate (mode_gate.apply_mode)."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from runtime.harness.hook_runner import mode_gate
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome
from yoke_contracts.hook_runner import lint_policy


def _deny() -> HookDecision:
    return HookDecision(outcome=Outcome.DENY, message="blocked", block=True, next=Next.STOP)


def _root_with_config(tmp_path: Path, name: str, text: str) -> Path:
    root = tmp_path / name
    (root / ".yoke").mkdir(parents=True)
    (root / ".yoke" / "lint-config").write_text(text, encoding="utf-8")
    return root


def _context(root: str | None) -> HookContext:
    return HookContext(
        event_name="PreToolUse",
        executor_family="codex",
        executor_surface="codex",
        payload={"tool_name": "Bash", "tool_input": {"command": "echo TC-1"}},
        tool_name="Bash",
        target_root=root,
    )


def _registered(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setattr(mode_gate.lint_config, "is_registered", lambda m: True)
    monkeypatch.setattr(mode_gate.lint_config, "resolve_mode", lambda m: mode)
    monkeypatch.setattr(mode_gate, "_emit_downgrade", lambda *a, **k: None)


def test_non_blocking_decision_is_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    _registered(monkeypatch, "warn")
    d = HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    assert mode_gate.apply_mode(d, "yoke_core.domain.lint_x") is d


def test_unregistered_blocking_decision_is_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mode_gate.lint_config, "is_registered", lambda m: False)
    d = _deny()
    assert mode_gate.apply_mode(d, "yoke_core.domain.not_a_guard") is d


def test_deny_mode_keeps_the_block(monkeypatch: pytest.MonkeyPatch) -> None:
    _registered(monkeypatch, "deny")
    d = _deny()
    out = mode_gate.apply_mode(d, "yoke_core.domain.lint_x")
    assert out is d and out.block is True


def test_warn_mode_downgrades_block_to_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    _registered(monkeypatch, "warn")
    out = mode_gate.apply_mode(_deny(), "yoke_core.domain.lint_x")
    assert out.outcome is Outcome.WARN
    assert out.next is Next.CONTINUE
    assert not out.block
    assert out.audit_fields.get("policy_mode") == "warn"
    assert out.audit_fields.get("downgraded_from") == Outcome.DENY.value


def test_context_target_root_warn_downgrades_even_when_ambient_denies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    yoke = _root_with_config(tmp_path, "yoke", "lint_tc_label=deny\n")
    buzz = _root_with_config(tmp_path, "buzz", "lint_tc_label=warn\n")
    monkeypatch.setenv("YOKE_TARGET_REPO_ROOT", str(yoke))
    monkeypatch.chdir(yoke)
    monkeypatch.setattr(mode_gate, "_emit_downgrade", lambda *a, **k: None)
    mode_gate.lint_config.reset_cache()

    out = mode_gate.apply_mode(
        _deny(), "yoke_core.domain.lint_tc_label", context=_context(str(buzz)),
    )

    assert out.outcome is Outcome.WARN
    assert out.next is Next.CONTINUE
    assert not out.block


def test_context_target_root_deny_keeps_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    yoke = _root_with_config(tmp_path, "yoke", "lint_tc_label=deny\n")
    buzz = _root_with_config(tmp_path, "buzz", "lint_tc_label=warn\n")
    monkeypatch.setenv("YOKE_TARGET_REPO_ROOT", str(buzz))
    monkeypatch.chdir(buzz)
    monkeypatch.setattr(mode_gate, "_emit_downgrade", lambda *a, **k: None)
    mode_gate.lint_config.reset_cache()

    out = mode_gate.apply_mode(
        _deny(), "yoke_core.domain.lint_tc_label", context=_context(str(yoke)),
    )

    assert out.outcome is Outcome.DENY
    assert out.next is Next.STOP
    assert out.block


def test_context_missing_or_unknown_target_root_fails_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambient = _root_with_config(tmp_path, "buzz", "lint_tc_label=warn\n")
    monkeypatch.setenv("YOKE_TARGET_REPO_ROOT", str(ambient))
    monkeypatch.chdir(ambient)
    monkeypatch.setattr(mode_gate, "_emit_downgrade", lambda *a, **k: None)
    mode_gate.lint_config.reset_cache()

    missing = mode_gate.apply_mode(
        _deny(), "yoke_core.domain.lint_tc_label", context=_context(None),
    )
    unknown = mode_gate.apply_mode(
        _deny(), "yoke_core.domain.lint_tc_label",
        context=_context(str(tmp_path / "not-a-repo")),
    )

    assert missing.outcome is Outcome.DENY
    assert unknown.outcome is Outcome.DENY


def test_payload_snapshot_warn_downgrades_without_server_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mode_gate, "_emit_downgrade", lambda *a, **k: None)
    context = _context(None)
    context.payload[lint_policy.SNAPSHOT_PAYLOAD_KEY] = {
        "lint_tc_label": {"mode": "warn"},
    }

    out = mode_gate.apply_mode(
        _deny(), "yoke_core.domain.lint_tc_label", context=context,
    )

    assert out.outcome is Outcome.WARN
    assert out.next is Next.CONTINUE
    assert not out.block


def test_protected_guard_warn_without_allow_warn_stays_deny_with_explicit_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root_with_config(tmp_path, "buzz", "lint_destructive_git=warn\n")
    monkeypatch.setattr(mode_gate, "_emit_downgrade", lambda *a, **k: None)
    mode_gate.lint_config.reset_cache()

    out = mode_gate.apply_mode(
        _deny(), "yoke_core.domain.lint_destructive_git", context=_context(str(root)),
    )

    assert out.outcome is Outcome.DENY
    assert out.block


def test_run_event_downgrades_warn_guard_and_chain_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: run_event applies the gate before the STOP check, so a
    warn-configured guard's deny is downgraded (command allowed) and the chain
    continues past it."""
    from runtime.harness.hook_runner import runner as runner_module
    from runtime.harness.hook_runner.adapter_capability import AdapterCapability
    from runtime.harness.hook_runner.decision_render import render_claude_decision

    class _Deny:
        @staticmethod
        def evaluate(context: object) -> HookDecision:  # noqa: ARG004
            return HookDecision(
                outcome=Outcome.DENY, message="blocked", block=True, next=Next.STOP,
            )

    class _After:
        ran = False

        @classmethod
        def evaluate(cls, context: object) -> HookDecision:  # noqa: ARG003
            cls.ran = True
            return HookDecision(outcome=Outcome.ALLOW, next=Next.CONTINUE)

    _After.ran = False
    mapping = {"mod.deny": _Deny, "mod.after": _After}
    real_import = importlib.import_module
    monkeypatch.setattr(
        importlib, "import_module",
        lambda name: mapping.get(name) or real_import(name),
    )
    monkeypatch.setattr(runner_module, "chain_for", lambda *a, **k: ["mod.deny", "mod.after"])
    for name in (
        "emit_hook_execution_failed",
        "emit_hook_guardrail_evaluated",
        "emit_hook_dispatch_telemetry",
    ):
        monkeypatch.setattr(runner_module._telemetry, name, lambda **k: None)
    # Configure the (synthetic) guard to warn; silence the downgrade audit emit.
    monkeypatch.setattr("yoke_core.domain.lint_config.is_registered", lambda m: True)
    monkeypatch.setattr(
        "yoke_core.domain.lint_config.resolve_mode",
        lambda m, *, root=None: "warn",
    )
    monkeypatch.setattr(mode_gate, "_emit_downgrade", lambda *a, **k: None)

    capability = AdapterCapability(
        family="claude",
        payload_parser=lambda raw: {"project_dir": str(Path.cwd())},
        decision_renderer=render_claude_decision,
    )
    text, exit_code = runner_module.run_event(
        "PreToolUse", capability=capability, stdin_data="{}",
    )

    assert exit_code == 0, "a warn-configured guard must not block the command"
    assert _After.ran, "chain must continue past a downgraded deny"
