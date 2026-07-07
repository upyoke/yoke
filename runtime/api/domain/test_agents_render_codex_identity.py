"""Codex hook command identity-safe regression tests.

Lives as a focused sibling of ``test_agents_render_substrate.py`` because the
parent test file is at the 350-line cap and the renderer-shape assertions for
the Codex executor/provider pin form one cohesive set.
"""

from __future__ import annotations

import json
import re

from yoke_core.domain.agents_render_codex import render_codex_hooks_json
from yoke_core.domain.agents_render_claude import render_claude_settings_json


def _codex_command_strings() -> list[str]:
    """Every rendered Codex hook command string, flattened across (event, matcher) pairs."""
    payload = json.loads(render_codex_hooks_json())
    commands: list[str] = []
    for entries in payload["hooks"].values():
        for entry in entries:
            for hook in entry.get("hooks", []):
                cmd = hook.get("command")
                if cmd:
                    commands.append(cmd)
    return commands


def _claude_command_strings() -> list[str]:
    """Every rendered Claude hook command string."""
    payload = json.loads(render_claude_settings_json())
    commands: list[str] = []
    for entries in payload["hooks"].values():
        for entry in entries:
            for hook in entry.get("hooks", []):
                cmd = hook.get("command")
                if cmd:
                    commands.append(cmd)
    return commands


def test_codex_hook_commands_pin_yoke_executor_codex() -> None:
    """Every Codex hook command sets ``YOKE_EXECUTOR=codex`` before the CLI."""
    commands = _codex_command_strings()
    assert commands, "renderer emitted zero Codex hook commands"
    pattern = re.compile(r"\benv\b[^']*?\bYOKE_EXECUTOR=codex\b")
    for cmd in commands:
        assert pattern.search(cmd), (
            f"Codex hook command missing YOKE_EXECUTOR=codex pin: {cmd!r}"
        )


def test_codex_hook_commands_pin_yoke_provider_openai() -> None:
    """Every Codex hook command sets ``YOKE_PROVIDER=openai`` before the CLI."""
    commands = _codex_command_strings()
    pattern = re.compile(r"\benv\b[^']*?\bYOKE_PROVIDER=openai\b")
    for cmd in commands:
        assert pattern.search(cmd), (
            f"Codex hook command missing YOKE_PROVIDER=openai pin: {cmd!r}"
        )


def test_codex_identity_env_precedes_yoke_cli() -> None:
    """The identity env vars must precede ``yoke hook evaluate``.

    Ordering matters: ``env A=1 B=2 cmd`` sets both before exec. We assert the
    identity pin lives on the same ``env`` invocation as the hook CLI.
    """
    for cmd in _codex_command_strings():
        env_clause = cmd.split("yoke hook evaluate", 1)[0]
        assert "YOKE_EXECUTOR=codex" in env_clause, (
            f"identity pin not in env clause before yoke CLI: {cmd!r}"
        )
        assert "YOKE_PROVIDER=openai" in env_clause, (
            f"provider pin not in env clause before yoke CLI: {cmd!r}"
        )
        assert env_clause.count("env ") == 1, (
            f"expected exactly one env wrapper, got: {cmd!r}"
        )


def test_codex_hook_commands_use_yoke_cli_without_repo_pythonpath() -> None:
    """Project hook configs call Yoke's CLI boundary, not local modules."""
    for cmd in _codex_command_strings():
        assert "yoke hook evaluate" in cmd, (
            f"Codex hook command missing yoke hook evaluate: {cmd!r}"
        )
        assert "runtime.harness.hook_runner" not in cmd, (
            f"Codex hook command leaked local hook_runner module: {cmd!r}"
        )
        assert "PYTHONPATH" not in cmd, (
            f"Codex hook command leaked repo-local PYTHONPATH: {cmd!r}"
        )


def test_claude_hook_commands_have_no_codex_identity_env() -> None:
    """Claude commands must not pick up Codex identity env vars."""
    for cmd in _claude_command_strings():
        assert "YOKE_EXECUTOR=codex" not in cmd, (
            f"Claude hook command incorrectly carries Codex executor pin: {cmd!r}"
        )
        assert "YOKE_PROVIDER=openai" not in cmd, (
            f"Claude hook command incorrectly carries Codex provider pin: {cmd!r}"
        )
