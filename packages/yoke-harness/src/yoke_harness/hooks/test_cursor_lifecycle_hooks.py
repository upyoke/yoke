"""Tests for Cursor hook root resolution and lifecycle user-hook backstop."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_contracts.cursor_hook_root import (
    parent_checkout_if_missing_worktree,
    resolve_existing_hook_root,
)
from yoke_harness.hooks.cursor_lifecycle_hooks import (
    cursor_lifecycle_hook_command,
    ensure_user_lifecycle_hooks,
)


def test_parent_checkout_peels_missing_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "yoke"
    repo.mkdir()
    missing = repo / ".worktrees" / "YOK-9999"
    assert parent_checkout_if_missing_worktree(str(missing)) == str(repo)
    assert parent_checkout_if_missing_worktree(str(repo)) == ""


def test_resolve_existing_hook_root_prefers_live_then_peel(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "checkout"
    repo.mkdir()
    dead = repo / ".worktrees" / "gone"
    assert resolve_existing_hook_root(str(dead), fallback="") == str(repo)
    live = tmp_path / "other"
    live.mkdir()
    # First existing candidate wins; a live path before a dead peel wins.
    assert resolve_existing_hook_root(
        str(live), str(dead), fallback="",
    ) == str(live)
    # A missing worktree peels before later candidates are consulted.
    assert resolve_existing_hook_root(
        str(dead), str(live), fallback="",
    ) == str(repo)


def test_lifecycle_command_peels_worktrees_and_marks() -> None:
    cmd = cursor_lifecycle_hook_command("Stop")
    assert "yoke-cursor-lifecycle-root=1" in cmd
    assert ".worktrees/" in cmd
    assert "yoke hook evaluate Stop" in cmd
    assert "YOKE_EXECUTOR=cursor" in cmd
    assert "YOKE_HOOK_CONFIG_OWNER=cursor-project" in cmd


def test_ensure_user_lifecycle_hooks_merges(tmp_path: Path) -> None:
    path = tmp_path / ".cursor" / "hooks.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({
            "version": 1,
            "hooks": {
                "stop": [{
                    "command": (
                        "/bin/zsh -lc 'echo >> /tmp/yoke-cursor-stop-canary.log'"
                    ),
                }],
                "afterFileEdit": [{"command": "echo keep"}],
            },
        }),
        encoding="utf-8",
    )
    assert ensure_user_lifecycle_hooks(hooks_path=path) is True
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["hooks"]["afterFileEdit"] == [{"command": "echo keep"}]
    stop_cmds = [e["command"] for e in payload["hooks"]["stop"]]
    assert any("yoke-cursor-lifecycle-root=1" in c for c in stop_cmds)
    assert any(
        "YOKE_HOOK_CONFIG_OWNER=cursor-user-lifecycle" in c
        for c in stop_cmds
    )
    assert not any("yoke-cursor-stop-canary" in c for c in stop_cmds)
    assert any(
        "yoke-cursor-lifecycle-root=1" in e["command"]
        for e in payload["hooks"]["sessionEnd"]
    )
    assert ensure_user_lifecycle_hooks(hooks_path=path) is False
