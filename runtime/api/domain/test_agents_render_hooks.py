"""Tests for ``yoke_core.domain.agents_render_hooks``.

Every Claude hook entry routes through one ``yoke hook evaluate <event>``
command, and a matcherless entry matches every tool — so events whose
chain applies via ``_default`` must render exactly one matcherless entry
rather than fanning the same command out across per-tool matchers.
"""

from __future__ import annotations

from yoke_harness.hooks import cursor_model_spool
from yoke_contracts.hook_runner.config_owner import (
    CURSOR_LIFECYCLE_COMMAND_MARKER,
    CURSOR_NATIVE_RUNNER_EVENTS,
)

from yoke_core.domain.agents_render_hooks import (
    _CURSOR_HOOK_TIMEOUT_S,
    render_claude_hooks_block,
    render_cursor_hooks_block,
)


def test_default_only_events_render_single_matcherless_entry() -> None:
    block = render_claude_hooks_block()
    for event in ("SessionStart", "SessionEnd", "Stop", "UserPromptSubmit"):
        entries = block[event]
        assert len(entries) == 1, (event, entries)
        assert "matcher" not in entries[0], (event, entries)


def test_posttool_events_have_no_redundant_per_tool_fanout() -> None:
    """The matcherless ``_default`` entry covers every tool; explicit
    matcher entries exist only for tools with their own registered chain."""
    block = render_claude_hooks_block()

    post = block["PostToolUse"]
    matcherless = [e for e in post if "matcher" not in e]
    assert len(matcherless) == 1, post
    assert {e["matcher"] for e in post if "matcher" in e} == {"Bash", "Agent"}

    post_failure = block["PostToolUseFailure"]
    assert len(post_failure) == 1, post_failure
    assert "matcher" not in post_failure[0], post_failure


def test_entries_are_unique_per_event() -> None:
    block = render_claude_hooks_block()
    for event, entries in block.items():
        matchers = [e.get("matcher") for e in entries]
        assert len(matchers) == len(set(matchers)), (event, matchers)


def test_claude_omits_verbs_no_claude_surface_fires() -> None:
    """The ordering registry is cross-harness. A verb only one harness
    reports must stay out of settings.json — Claude disables every hook in
    the file when one entry fails validation."""
    block = render_claude_hooks_block()
    assert "AgentModelReported" not in block


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


def test_model_capture_hook_never_starts_the_interpreter() -> None:
    """``afterAgentThought`` fires inside the token stream, where starting
    Python already exceeds what Cursor tolerates — a 0.25s hook carrying no
    Yoke code at all kills 4 of 6 runs. Its command must stay shell-only and
    must still reply, since empty stdout drops the stream too."""
    entries = render_cursor_hooks_block()["hooks"]["afterAgentThought"]
    assert len(entries) == 1, entries
    command = entries[0]["command"]
    assert "yoke hook evaluate" not in command, command
    assert "python" not in command.lower(), command
    assert command.rstrip("'").endswith("echo {}"), command


def test_model_capture_hook_and_reader_share_one_directory() -> None:
    """The shell writes the spool and Python reads it; the directory name
    has to come from the same constant or they silently miss each other."""
    command = render_cursor_hooks_block()["hooks"]["afterAgentThought"][0]["command"]
    assert cursor_model_spool.SPOOL_DIR_NAME in command
    assert cursor_model_spool.SPOOL_DIR_NAME == cursor_model_spool.spool_dir().name


def test_cursor_entries_carry_explicit_timeout() -> None:
    """Every rendered Cursor hook entry pins an explicit generous timeout
    so a slow relay is bounded by our ceiling, not the platform default."""
    document = render_cursor_hooks_block()
    assert document["version"] == 1
    for event, entries in document["hooks"].items():
        for entry in entries:
            assert entry.get("timeout") == _CURSOR_HOOK_TIMEOUT_S, (event, entry)
    assert _CURSOR_HOOK_TIMEOUT_S >= 30


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
        "YOKE_HOOK_CONFIG_OWNER=cursor-project" in command
        for command in commands
    )
    for native_event, runner_event in CURSOR_NATIVE_RUNNER_EVENTS:
        assert any(
            f"yoke hook evaluate {runner_event}" in entry["command"]
            for entry in block["hooks"][native_event]
        )
