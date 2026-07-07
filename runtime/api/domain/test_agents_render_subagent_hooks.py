"""Tests for yoke_core.domain.agents_render_subagent_hooks.

Covers the subagent hook rendering acceptance criteria:

- The composer walks ``HOOK_ORDERING["PreToolUse"]`` and emits one
  ``YOKE_HOOK_AGENT_TYPE=<role> yoke hook evaluate PreToolUse``
  entry per matcher with a non-empty registered chain.
- Non-Bash subagents (PM/PD) get only matchers whose tool is granted; the
  Bash-only matchers (Bash / Monitor / ScheduleWakeup / TaskOutput) are
  omitted.
- The composer wraps every emitted command with the shell-builtin
  ``YOKE_HOOK_AGENT_TYPE=<role>`` env prefix (no ``env`` binary so
  HC-agent-consistency's executable classifier reads the real head).
- PostToolUse / PostToolUseFailure observe entries carry both the env
  prefix and ``--agent-type <role>`` flag (preserves the existing
  telemetry agent-type attribution).
- SubagentStop wraps ``agent_stop`` with the env prefix.
"""

from __future__ import annotations

from yoke_core.domain.agents_render_subagent_hooks import (
    is_bash_capable_subagent,
    render_claude_subagent_hooks_block,
)
from yoke_contracts.hook_runner.hook_ordering import (
    matchers_for,
    ordered_pipeline_for,
)


_BASH_CAPABLE_ROLES = ("engineer", "tester", "architect", "boss", "simulator")
_NON_BASH_ROLES = ("product-manager", "product-designer")


def _engineer_tools() -> str:
    return "Read, Write, Edit, Bash, Grep, Glob, Monitor"


def _tester_tools() -> str:
    return "Read, Grep, Glob, Bash, Monitor"


def _architect_tools() -> str:
    return "Read, Grep, Glob, Bash"


def _boss_tools() -> str:
    return "Read, Grep, Glob, Bash"


def _simulator_tools() -> str:
    return "Read, Grep, Glob, Bash"


def _pm_tools() -> str:
    return "Read, Grep, Glob"


def _pd_tools() -> str:
    return "Read, Grep, Glob"


_TOOLS_BY_ROLE = {
    "engineer": _engineer_tools(),
    "tester": _tester_tools(),
    "architect": _architect_tools(),
    "boss": _boss_tools(),
    "simulator": _simulator_tools(),
    "product-manager": _pm_tools(),
    "product-designer": _pd_tools(),
}


def test_is_bash_capable_subagent_recognises_bash_grant() -> None:
    for role in _BASH_CAPABLE_ROLES:
        assert is_bash_capable_subagent(_TOOLS_BY_ROLE[role]) is True, role
    for role in _NON_BASH_ROLES:
        assert is_bash_capable_subagent(_TOOLS_BY_ROLE[role]) is False, role


def _expected_pretool_matchers() -> list[str]:
    """Universal PreToolUse matchers a Bash-capable subagent should cover."""
    expected: list[str] = []
    for matcher in matchers_for("PreToolUse"):
        if matcher in {"_default", "apply_patch"}:
            continue
        if not ordered_pipeline_for("PreToolUse", matcher):
            continue
        expected.append(matcher)
    return expected


def test_bash_capable_subagents_cover_every_pretool_matcher() -> None:
    expected = _expected_pretool_matchers()
    # Each Bash-capable subagent emits one entry per universal
    # PreToolUse matcher (Bash, Edit, Write, Read, Monitor, ScheduleWakeup,
    # TaskOutput today; new entries propagate from HOOK_ORDERING).
    assert len(expected) == 7, expected
    for role in _BASH_CAPABLE_ROLES:
        block = render_claude_subagent_hooks_block(role, tools=_TOOLS_BY_ROLE[role])
        pre = block.get("PreToolUse", [])
        rendered_matchers = [entry["matcher"] for entry in pre]
        assert rendered_matchers == expected, (role, rendered_matchers)


def test_bash_capable_subagent_pretool_commands_are_env_wrapped_runner() -> None:
    for role in _BASH_CAPABLE_ROLES:
        block = render_claude_subagent_hooks_block(role, tools=_TOOLS_BY_ROLE[role])
        for entry in block.get("PreToolUse", []):
            assert len(entry["hooks"]) == 1, entry
            command = entry["hooks"][0]["command"]
            expected = (
                f"YOKE_HOOK_AGENT_TYPE={role} "
                f"yoke hook evaluate PreToolUse"
            )
            assert command == expected, (role, entry["matcher"], command)
            # No --agent-type CLI flag on rendered PreToolUse commands.
            assert "--agent-type" not in command, (role, command)


def test_non_bash_subagents_omit_bash_only_matchers() -> None:
    bash_only = {"Bash", "Monitor", "ScheduleWakeup", "TaskOutput"}
    for role in _NON_BASH_ROLES:
        block = render_claude_subagent_hooks_block(role, tools=_TOOLS_BY_ROLE[role])
        for entry in block.get("PreToolUse", []):
            assert entry["matcher"] not in bash_only, (role, entry["matcher"])


def test_non_bash_subagents_emit_no_lint_subagent_background_chain() -> None:
    # ``lint_subagent_background`` only lives in chains keyed on Bash, Monitor,
    # ScheduleWakeup, and TaskOutput. A PM/PD subagent that doesn't emit any
    # of those matchers cannot route a Bash-capable subagent lint.
    matchers_with_lint = {
        matcher
        for matcher in matchers_for("PreToolUse")
        if "yoke_core.domain.lint_subagent_background"
        in ordered_pipeline_for("PreToolUse", matcher)
    }
    assert matchers_with_lint == {"Bash", "Monitor", "ScheduleWakeup", "TaskOutput"}
    for role in _NON_BASH_ROLES:
        block = render_claude_subagent_hooks_block(role, tools=_TOOLS_BY_ROLE[role])
        rendered = {entry["matcher"] for entry in block.get("PreToolUse", [])}
        assert rendered.isdisjoint(matchers_with_lint), (role, rendered)


def test_posttool_observe_command_includes_env_prefix_and_agent_type() -> None:
    for role in _BASH_CAPABLE_ROLES + _NON_BASH_ROLES:
        block = render_claude_subagent_hooks_block(role, tools=_TOOLS_BY_ROLE[role])
        for event_name in ("PostToolUse", "PostToolUseFailure"):
            entries = block.get(event_name, [])
            assert len(entries) == 1, (role, event_name, entries)
            command = entries[0]["hooks"][0]["command"]
            assert command.startswith(f"YOKE_HOOK_AGENT_TYPE={role} "), (
                role,
                event_name,
                command,
            )
            assert f"--agent-type {role}" in command, (role, event_name, command)
            assert f"--hook-event {event_name}" in command, (
                role,
                event_name,
                command,
            )


def test_subagent_stop_runs_agent_stop_with_env_prefix() -> None:
    for role in _BASH_CAPABLE_ROLES + _NON_BASH_ROLES:
        block = render_claude_subagent_hooks_block(role, tools=_TOOLS_BY_ROLE[role])
        entries = block.get("SubagentStop", [])
        assert len(entries) == 1, (role, entries)
        command = entries[0]["hooks"][0]["command"]
        expected = (
            f"YOKE_HOOK_AGENT_TYPE={role} "
            f"python3 -m yoke_core.domain.agent_stop"
        )
        assert command == expected, (role, command)
