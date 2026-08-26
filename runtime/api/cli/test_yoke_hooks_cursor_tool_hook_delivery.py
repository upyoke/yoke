"""Cursor tool-call hooks must survive an imported Claude hook config.

A workspace carrying both `.cursor/hooks.json` and `.claude/settings.json`
routes every Cursor tool call through the imported Claude hooks alone —
Cursor stops firing its own beforeShellExecution / afterShellExecution /
preToolUse / postToolUse there. Discarding that invocation as a duplicate
leaves the session with no tool-shaped hook at all: no guards, no
telemetry, no heartbeat, and no inbound message injection.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from yoke_cli.commands.adapters.hook_config_dedup import (
    should_skip_config_duplicate,
)
from yoke_cli.main import main as cli_main


def _write_cursor_owner(
    root: Path,
    native_events: str | tuple[str, ...],
    runner_event: str,
) -> None:
    cursor = root / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    if isinstance(native_events, str):
        native_events = (native_events,)
    (cursor / "hooks.json").write_text(
        json.dumps(
            {
                "version": 1,
                "hooks": {
                    native_event: [
                        {
                            "command": (
                                "env YOKE_HOOK_CONFIG_OWNER=cursor-project "
                                f"yoke hook evaluate {runner_event}"
                            ),
                            "timeout": 30,
                        }
                    ]
                    for native_event in native_events
                },
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("runner_event", "native_event", "native_runner_event"),
    (
        ("PreToolUse", ("beforeShellExecution", "preToolUse"), "PreToolUse"),
        ("PreToolUse", "preToolUse", "PreToolUse"),
        (
            "PermissionRequest",
            ("beforeShellExecution", "preToolUse"),
            "PreToolUse",
        ),
        ("PostToolUse", ("afterShellExecution", "postToolUse"), "PostToolUse"),
        ("PostToolUse", "postToolUse", "PostToolUse"),
        ("PostToolUseFailure", "postToolUseFailure", "PostToolUseFailure"),
    ),
)
def test_imported_claude_tool_hook_is_never_a_duplicate(
    tmp_path,
    runner_event,
    native_event,
    native_runner_event,
) -> None:
    """A tool call fires the imported Claude hook and nothing else.

    Cursor stops firing its own beforeShellExecution / afterShellExecution /
    preToolUse / postToolUse once a workspace carries `.claude/settings.json`,
    so a native owner entry for the same verb proves nothing about a second
    invocation — skipping here drops the tool call's only hook.
    """
    _write_cursor_owner(tmp_path, native_event, native_runner_event)
    environment = {
        "YOKE_HOOK_CONFIG_OWNER": "claude",
        "CURSOR_PROJECT_DIR": str(tmp_path),
    }
    payload = '{"session_id":"cursor-tool","conversation_id":"cursor-tool"}'

    assert not should_skip_config_duplicate(
        runner_event,
        environment,
        payload,
    )


@pytest.mark.parametrize(
    ("runner_event", "native_events"),
    (
        ("PreToolUse", ("beforeShellExecution", "preToolUse")),
        ("PostToolUse", ("afterShellExecution", "postToolUse")),
    ),
)
def test_imported_claude_tool_hook_reaches_transport(
    monkeypatch,
    tmp_path,
    runner_event,
    native_events,
) -> None:
    """The tool call's one hook must run the chain, not exit early."""
    _write_cursor_owner(tmp_path, native_events, runner_event)
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            '{"session_id":"cursor-live","conversation_id":"cursor-live",'
            '"tool_name":"Shell","tool_use_id":"tool-1"}'
        ),
    )
    monkeypatch.setenv("YOKE_HOOK_CONFIG_OWNER", "claude")
    monkeypatch.setenv("CURSOR_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection",
        lambda: (_ for _ in ()).throw(RuntimeError("transport reached")),
    )

    with pytest.raises(RuntimeError, match="transport reached"):
        cli_main(["hook", "evaluate", runner_event])
