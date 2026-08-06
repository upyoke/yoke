"""Cursor deduplication for Claude-compatible project hook imports."""

from __future__ import annotations

import io
import sys

from yoke_cli.main import main as cli_main


def test_cursor_imported_claude_hook_exits_before_transport(
    monkeypatch,
) -> None:
    unread = io.StringIO('{"session_id": "must-not-be-read"}')
    monkeypatch.setattr(sys, "stdin", unread)
    monkeypatch.setenv("YOKE_HOOK_CONFIG_OWNER", "claude")
    monkeypatch.setenv("CURSOR_PROJECT_DIR", "/project")
    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection",
        lambda: (_ for _ in ()).throw(
            AssertionError("deduplicated hook must not resolve transport")
        ),
    )

    assert cli_main(["hook", "evaluate", "SessionStart"]) == 0
    assert unread.tell() == 0


def test_claude_owned_hook_still_runs_outside_cursor(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_HOOK_CONFIG_OWNER", "claude")
    for key in (
        "CURSOR_PROJECT_DIR",
        "CURSOR_TRANSCRIPT_PATH",
        "CURSOR_INVOKED_AS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection",
        lambda: (_ for _ in ()).throw(RuntimeError("transport reached")),
    )

    try:
        cli_main(["hook", "evaluate", "SessionStart"])
    except RuntimeError as exc:
        assert str(exc) == "transport reached"
    else:
        raise AssertionError("Claude-owned hook was incorrectly deduplicated")
