"""Unit tests for the hook_runner foundational dataclasses.

The full runner test suite (`test_hook_runner.py`) lands in Task 014; this
file is scoped to the dataclasses created in Task 001.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timezone

import pytest

from runtime.harness.hook_runner import (
    AdapterCapability,
    HookContext,
    HookDecision,
    Next,
    Outcome,
)


# ---------------------------------------------------------------------------
# AC-T1: top-level imports succeed.
# ---------------------------------------------------------------------------


def test_top_level_imports_resolve() -> None:
    """`from runtime.harness.hook_runner import ...` succeeds (AC-T1)."""

    assert HookContext is not None
    assert HookDecision is not None
    assert AdapterCapability is not None


# ---------------------------------------------------------------------------
# HookContext / HookDecision are frozen dataclasses with the spec shape.
# ---------------------------------------------------------------------------


def test_hookcontext_constructs_with_spec_fields() -> None:
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    ctx = HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude-desktop",
        payload={"tool_name": "Bash"},
        tool_name="Bash",
        command_body="echo hi",
        cwd="/tmp",
        target_root="/tmp/repo",
        session_id="sess-1",
        item_id=1638,
        now=now,
    )
    assert ctx.event_name == "PreToolUse"
    assert ctx.executor_family == "claude"
    assert ctx.payload == {"tool_name": "Bash"}
    assert ctx.tool_name == "Bash"
    assert ctx.command_body == "echo hi"
    assert ctx.cwd == "/tmp"
    assert ctx.target_root == "/tmp/repo"
    assert ctx.session_id == "sess-1"
    assert ctx.item_id == 1638
    assert ctx.now == now


def test_hookcontext_optional_fields_default_to_none() -> None:
    ctx = HookContext(
        event_name="SessionStart",
        executor_family="codex",
        executor_surface="codex-vscode",
        payload={},
    )
    assert ctx.tool_name is None
    assert ctx.command_body is None
    assert ctx.cwd is None
    assert ctx.target_root is None
    assert ctx.session_id is None
    assert ctx.item_id is None
    assert ctx.now is None


def test_hookcontext_is_frozen() -> None:
    ctx = HookContext(
        event_name="SessionStart",
        executor_family="claude",
        executor_surface="claude-desktop",
        payload={},
    )
    with pytest.raises(FrozenInstanceError):
        ctx.event_name = "PreToolUse"  # type: ignore[misc]


def test_hookdecision_constructs_with_defaults() -> None:
    decision = HookDecision(outcome=Outcome.ALLOW)
    assert decision.outcome is Outcome.ALLOW
    assert decision.message == ""
    assert decision.audit_fields == {}
    assert decision.block is False
    assert decision.next is Next.CONTINUE


def test_hookdecision_full_payload() -> None:
    decision = HookDecision(
        outcome=Outcome.DENY,
        message="banned",
        audit_fields={"rule": "lint_x"},
        block=True,
        next=Next.STOP,
    )
    assert decision.outcome is Outcome.DENY
    assert decision.message == "banned"
    assert decision.audit_fields == {"rule": "lint_x"}
    assert decision.block is True
    assert decision.next is Next.STOP


def test_hookdecision_is_frozen() -> None:
    decision = HookDecision(outcome=Outcome.ALLOW)
    with pytest.raises(FrozenInstanceError):
        decision.message = "mutated"  # type: ignore[misc]


def test_outcome_and_next_value_sets_match_spec() -> None:
    """Closed sets named in the epic spec stay closed."""

    assert {o.value for o in Outcome} == {
        "allow",
        "deny",
        "warn",
        "suppression_attempted",
        "audit_only",
        "noop",
    }
    assert {n.value for n in Next} == {"continue", "stop"}


# ---------------------------------------------------------------------------
# AC-2 / AC-T2 / AC-T3: AdapterCapability shape including subprocess_modules.
# ---------------------------------------------------------------------------


def _stub_parser(*_: object, **__: object) -> dict[str, object]:
    return {}


def _stub_renderer(*_: object, **__: object) -> tuple[str, int]:
    return ("", 0)


def test_adapter_capability_has_expected_field_set() -> None:
    """Field list matches the epic spec, including the new subprocess_modules slot."""

    field_names = {f.name for f in fields(AdapterCapability)}
    assert field_names == {
        "family",
        "events",
        "payload_parser",
        "decision_renderer",
        "apply_patch_chain_omissions",
        "pretool_omissions",
        "subprocess_modules",
    }


def test_adapter_capability_default_subprocess_modules_is_empty() -> None:
    """AC-T2: default `subprocess_modules` is the empty frozenset."""

    cap = AdapterCapability(
        "x",
        frozenset(),
        _stub_parser,
        _stub_renderer,
    )
    assert cap.subprocess_modules == frozenset()
    assert isinstance(cap.subprocess_modules, frozenset)
    assert cap.apply_patch_chain_omissions == frozenset()
    assert cap.pretool_omissions == frozenset()


def test_adapter_capability_populated_subprocess_modules_round_trips() -> None:
    """AC-T3: an explicit `subprocess_modules` value survives construction."""

    cap = AdapterCapability(
        "x",
        frozenset(),
        _stub_parser,
        _stub_renderer,
        subprocess_modules=frozenset({"yoke_core.domain.observe"}),
    )
    assert cap.subprocess_modules == frozenset({"yoke_core.domain.observe"})


def test_adapter_capability_is_frozen() -> None:
    cap = AdapterCapability(
        "x",
        frozenset(),
        _stub_parser,
        _stub_renderer,
    )
    with pytest.raises(FrozenInstanceError):
        cap.family = "y"  # type: ignore[misc]
