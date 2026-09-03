"""Tests for ``yoke_core.domain.agents_render_hooks``.

Every Claude hook entry routes through one ``yoke hook evaluate <event>``
command, and a matcherless entry matches every tool — so events whose
chain applies via ``_default`` must render exactly one matcherless entry
rather than fanning the same command out across per-tool matchers.
"""

from __future__ import annotations

from yoke_contracts.hook_runner.config_owner import (
    CURSOR_LIFECYCLE_COMMAND_MARKER,
    CURSOR_NATIVE_RUNNER_EVENTS,
)

from yoke_core.domain.agents_render_hooks import (
    _CURSOR_HOOK_TIMEOUT_S,
    _CURSOR_NON_SHELL_TOOL_MATCHER,
    render_claude_hooks_block,
    render_codex_hooks_block,
    render_cursor_hooks_block,
)


def test_claude_events_render_single_matcherless_dispatch() -> None:
    block = render_claude_hooks_block()
    for event in (
        "SessionStart",
        "SessionEnd",
        "Stop",
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
    ):
        entries = block[event]
        assert len(entries) == 1, (event, entries)
        assert "matcher" not in entries[0], (event, entries)


def test_posttool_events_have_no_redundant_per_tool_fanout() -> None:
    """One matcherless dispatch lets the runner select each tool's chain."""
    block = render_claude_hooks_block()

    post = block["PostToolUse"]
    assert len(post) == 1, post
    assert "matcher" not in post[0], post

    post_failure = block["PostToolUseFailure"]
    assert len(post_failure) == 1, post_failure
    assert "matcher" not in post_failure[0], post_failure


def test_entries_are_unique_per_event() -> None:
    block = render_claude_hooks_block()
    for event, entries in block.items():
        matchers = [e.get("matcher") for e in entries]
        assert len(matchers) == len(set(matchers)), (event, matchers)


def test_claude_commands_mark_their_config_owner() -> None:
    """Cursor imports Claude settings, so the CLI needs source ownership
    to no-op those entries when native Cursor hooks are also installed."""
    block = render_claude_hooks_block()
    commands = [
        hook["command"]
        for entries in block.values()
        for entry in entries
        for hook in entry["hooks"]
    ]
    assert commands
    assert all("YOKE_HOOK_CONFIG_OWNER=claude" in command for command in commands)


def test_generated_hook_commands_use_non_login_shell_with_launcher_path() -> None:
    claude = render_claude_hooks_block()
    codex = render_codex_hooks_block()
    cursor = render_cursor_hooks_block()["hooks"]
    commands = [
        hook["command"]
        for block in (claude, codex)
        for entries in block.values()
        for entry in entries
        for hook in entry["hooks"]
    ] + [entry["command"] for entries in cursor.values() for entry in entries]

    assert commands
    assert all(command.startswith("/bin/sh -c '") for command in commands)
    assert all("/bin/zsh" not in command for command in commands)
    assert all("${XDG_BIN_HOME:-$HOME/.local/bin}" in command for command in commands)


def test_no_hook_is_wired_inside_the_token_stream() -> None:
    """``afterAgentThought`` fires inside the generation stream with the
    stream held open across the hook, and on cursor-agent 2026.08.25 a hook
    there breaks the stream whatever it replies - a bare ``exit 0`` and a
    plain ``echo {}`` each did, one break per thought, until the reconnects
    ran out. Nothing is lost by leaving it unwired: the events that open and
    close a session name the model themselves."""
    assert "afterAgentThought" not in render_cursor_hooks_block()["hooks"]


def test_cursor_entries_carry_explicit_timeout() -> None:
    """Every rendered Cursor hook entry pins an explicit generous timeout
    so a slow relay is bounded by our ceiling, not the platform default."""
    document = render_cursor_hooks_block()
    assert document["version"] == 1
    for event, entries in document["hooks"].items():
        for entry in entries:
            assert entry.get("timeout") == _CURSOR_HOOK_TIMEOUT_S, (event, entry)
    assert _CURSOR_HOOK_TIMEOUT_S >= 30


def test_cursor_pre_post_matchers_cover_every_tool_except_shell() -> None:
    """Shell stays on before/afterShellExecution; everything else must match."""
    block = render_cursor_hooks_block()["hooks"]
    assert block["preToolUse"][0]["matcher"] == _CURSOR_NON_SHELL_TOOL_MATCHER
    assert block["postToolUse"][0]["matcher"] == _CURSOR_NON_SHELL_TOOL_MATCHER


def test_cursor_stop_and_session_end_use_lifecycle_command() -> None:
    """Stop/sessionEnd peel a deleted worktree cwd; ordinary tool hooks do not."""
    block = render_cursor_hooks_block()
    stop = block["hooks"]["stop"][0]["command"]
    end = block["hooks"]["sessionEnd"][0]["command"]
    assert CURSOR_LIFECYCLE_COMMAND_MARKER in stop
    assert CURSOR_LIFECYCLE_COMMAND_MARKER in end
    pre = block["hooks"]["preToolUse"][0]["command"]
    assert CURSOR_LIFECYCLE_COMMAND_MARKER not in pre


def test_cursor_runner_commands_mark_the_project_config_owner() -> None:
    block = render_cursor_hooks_block()
    commands = [
        entry["command"]
        for entries in block["hooks"].values()
        for entry in entries
        if "yoke hook evaluate" in entry["command"]
    ]
    assert commands
    assert all(
        "YOKE_HOOK_CONFIG_OWNER=cursor-project" in command for command in commands
    )
    for native_event, runner_event in CURSOR_NATIVE_RUNNER_EVENTS:
        assert any(
            f"yoke hook evaluate {runner_event}" in entry["command"]
            for entry in block["hooks"][native_event]
        )
