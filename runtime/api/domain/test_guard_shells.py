"""Every shell-chain rule declares its shells; dispatch honors the declaration."""

from __future__ import annotations

import pytest

from yoke_contracts.hook_runner.guard_shells import (
    GUARD_SHELLS,
    guard_shells,
    shell_applicable_chain,
)
from yoke_contracts.hook_runner.hook_ordering import ordered_pipeline_for
from yoke_core.domain.harness_policy_pipeline import (
    build_tool_event_record,
    dispatch,
    shell_kind_for_tool,
    tool_kind_for,
)
from yoke_core.domain.observe_tool_event import TOOL_KIND_SHELL

_SHELL_CHAINS = (("PreToolUse", "Bash"), ("PostToolUse", "Bash"))


def _shell_chain_rules() -> set[str]:
    rules: set[str] = set()
    for event, matcher in _SHELL_CHAINS:
        for module_id in ordered_pipeline_for(event, matcher):
            if module_id.startswith("yoke_core.domain."):
                rules.add(module_id)
    return rules


def test_every_shell_chain_rule_declares_its_shells() -> None:
    rules = _shell_chain_rules()
    assert rules <= set(GUARD_SHELLS), sorted(rules - set(GUARD_SHELLS))
    for module_id in rules:
        assert guard_shells(module_id) & {"bash"}, module_id


def test_declarations_name_only_shell_chain_rules() -> None:
    assert set(GUARD_SHELLS) <= _shell_chain_rules()


def test_undeclared_rule_is_a_named_refusal() -> None:
    with pytest.raises(ValueError, match="hook_guard_shells_missing"):
        shell_applicable_chain(["yoke_core.domain.lint_new_rule"], "powershell")
    assert shell_applicable_chain(["yoke_core.hooks.heartbeat"], "powershell") == [
        "yoke_core.hooks.heartbeat"
    ]


@pytest.mark.parametrize("module_id", sorted(GUARD_SHELLS))
def test_each_rule_runs_for_bash_and_only_declared_rules_for_powershell(module_id) -> None:
    chain = ordered_pipeline_for("PreToolUse", "Bash") + ordered_pipeline_for(
        "PostToolUse", "Bash"
    )
    assert module_id in shell_applicable_chain(chain, "bash")
    covered = module_id in shell_applicable_chain(chain, "powershell")
    assert covered is ("powershell" in GUARD_SHELLS[module_id])


def test_non_shell_chains_are_not_filtered() -> None:
    chain = ordered_pipeline_for("PreToolUse", "Write")
    assert shell_applicable_chain(chain, None) == chain


@pytest.mark.parametrize("tool", ["Bash", "PowerShell", "shell", "Shell"])
def test_every_harness_shell_tool_is_the_shell_kind(tool: str) -> None:
    assert tool_kind_for(tool) == TOOL_KIND_SHELL


def test_pipeline_records_carry_the_harness_shell() -> None:
    def record(harness: str, tool: str, windows: bool):
        return build_tool_event_record(
            tool_name=tool,
            tool_input={"command": "ls"},
            harness_id=harness,
            windows=windows,
        )

    assert record("claude-code", "PowerShell", False).shell_kind == "powershell"
    assert record("claude-code", "Bash", True).shell_kind == "bash"
    assert record("codex", "shell", True).shell_kind == "powershell"
    assert record("cursor", "Shell", False).shell_kind == "bash"
    assert shell_kind_for_tool("", "PowerShell") == "powershell"


def test_pipeline_dispatch_skips_bash_only_rules_for_powershell(monkeypatch) -> None:
    called: list[str] = []

    def _resolve(module_id):
        return lambda rec: called.append(module_id)

    monkeypatch.setattr(
        "yoke_core.domain.harness_policy_pipeline._resolve_policy_callable", _resolve
    )
    rec = build_tool_event_record(
        tool_name="PowerShell", tool_input={"command": "ls"}, harness_id="claude-code"
    )
    dispatch(rec)
    assert "yoke_core.domain.path_claim_bash_guard" in called
    assert "yoke_core.domain.lint_shell_backtick_search" not in called
