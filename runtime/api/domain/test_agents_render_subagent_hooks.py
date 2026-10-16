"""Tests for yoke_core.domain.agents_render_subagent_hooks.

Covers the subagent hook rendering acceptance criteria:

- The composer emits one matcherless
  ``YOKE_HOOK_AGENT_TYPE=<role> yoke hook evaluate PreToolUse``
  entry so every tool reaches the runner; chain selection stays in
  ``HOOK_ORDERING`` keyed by ``tool_name``.
- The composer wraps every emitted command with the shell-builtin
  ``YOKE_HOOK_AGENT_TYPE=<role>`` env prefix (no ``env`` binary so
  HC-agent-consistency's executable classifier reads the real head).
- PostToolUse / PostToolUseFailure share the transport-aware runner
  and preserve role attribution.
- SubagentStop wraps ``agent_stop`` with the env prefix.
"""

from __future__ import annotations

from yoke_core.domain.agents_render_subagent_hooks import (
    render_claude_subagent_hooks_block,
)
from yoke_contracts.hook_runner.hook_ordering import (
    matchers_for,
    ordered_pipeline_for,
)


_BASH_CAPABLE_ROLES = (
    "engineer",
    "tester",
    "architect",
    "boss",
    "simulator",
    "qa-walker",
)
_NON_BASH_ROLES = ("product-manager", "product-designer")


def test_subagent_pretool_is_matcherless_runner() -> None:
    for role in _BASH_CAPABLE_ROLES + _NON_BASH_ROLES:
        block = render_claude_subagent_hooks_block(role)
        pre = block.get("PreToolUse", [])
        assert len(pre) == 1, (role, pre)
        assert "matcher" not in pre[0], (role, pre[0])
        command = pre[0]["hooks"][0]["command"]
        expected = (
            "YOKE_HOOK_CONFIG_OWNER=claude "
            f"YOKE_HOOK_AGENT_TYPE={role} "
            "yoke hook evaluate PreToolUse"
        )
        assert command == expected, (role, command)
        assert "--agent-type" not in command, (role, command)


def test_lint_subagent_background_stays_on_bash_family_matchers() -> None:
    matchers_with_lint = {
        matcher
        for matcher in matchers_for("PreToolUse")
        if "yoke_core.domain.lint_subagent_background"
        in ordered_pipeline_for("PreToolUse", matcher)
    }
    assert matchers_with_lint == {"Bash", "Monitor", "ScheduleWakeup", "TaskOutput"}


def test_posttool_events_use_transport_aware_runner() -> None:
    for role in _BASH_CAPABLE_ROLES + _NON_BASH_ROLES:
        block = render_claude_subagent_hooks_block(role)
        for event_name in ("PostToolUse", "PostToolUseFailure"):
            entries = block.get(event_name, [])
            assert len(entries) == 1, (role, event_name, entries)
            assert "matcher" not in entries[0], (role, event_name, entries[0])
            command = entries[0]["hooks"][0]["command"]
            assert command.startswith(
                f"YOKE_HOOK_CONFIG_OWNER=claude YOKE_HOOK_AGENT_TYPE={role} "
            ), (
                role,
                event_name,
                command,
            )
            assert command.endswith(f"yoke hook evaluate {event_name}"), command


def test_subagent_stop_runs_agent_stop_with_env_prefix() -> None:
    for role in _BASH_CAPABLE_ROLES + _NON_BASH_ROLES:
        block = render_claude_subagent_hooks_block(role)
        entries = block.get("SubagentStop", [])
        assert len(entries) == 1, (role, entries)
        command = entries[0]["hooks"][0]["command"]
        expected = (
            "YOKE_HOOK_CONFIG_OWNER=claude "
            f"YOKE_HOOK_AGENT_TYPE={role} "
            f"python3 -m yoke_core.domain.agent_stop"
        )
        assert command == expected, (role, command)
