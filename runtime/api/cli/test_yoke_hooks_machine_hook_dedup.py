"""Machine-wide hooks step aside when the project's own hooks own the event.

One rule for every harness and every event, tool events included. The
project file owns an event through any non-machine-wide ``yoke hook
evaluate <Verb>`` entry, so an older project render without an owner marker
still counts; a file the harness would reject owns nothing.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from yoke_cli.commands.adapters.hook_config_dedup import should_skip_config_duplicate
from yoke_cli.main import main as cli_main
from yoke_core.domain.agents_render_hooks import (
    render_claude_hooks_block,
    render_codex_hooks_block,
    render_cursor_hooks_block,
)

CURSOR_PAYLOAD = '{"session_id":"c-1","conversation_id":"c-1"}'


def _write_project(root: Path, harness_id: str) -> None:
    """The real project render for one harness, as setup installs it."""
    if harness_id == "claude-code":
        path, document = root / ".claude/settings.json", {"hooks": render_claude_hooks_block()}
    elif harness_id == "codex":
        path, document = root / ".codex/hooks.json", {"hooks": render_codex_hooks_block()}
    else:
        path, document = root / ".cursor/hooks.json", render_cursor_hooks_block()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def _environment(harness_id: str, root: Path) -> dict[str, str]:
    owner = {"claude-code": "claude-user", "codex": "codex-user", "cursor": "cursor-user"}
    env = {"YOKE_HOOK_CONFIG_OWNER": owner[harness_id], "HOME": str(root / "home")}
    if harness_id == "claude-code":
        env["CLAUDE_PROJECT_DIR"] = str(root)
    if harness_id == "cursor":
        env["CURSOR_PROJECT_DIR"] = str(root)
    return env


def _payload(harness_id: str, root: Path) -> str:
    if harness_id == "cursor":
        return json.dumps({"session_id": "c-1", "conversation_id": "c-1", "cwd": str(root)})
    return json.dumps({"session_id": "s-1", "cwd": str(root)})


@pytest.mark.parametrize("harness_id", ("claude-code", "codex", "cursor"))
@pytest.mark.parametrize("verb", ("SessionStart", "UserPromptSubmit", "PreToolUse", "Stop"))
def test_user_hook_steps_aside_inside_a_project(tmp_path, harness_id, verb):
    _write_project(tmp_path, harness_id)
    env = _environment(harness_id, tmp_path)
    assert should_skip_config_duplicate(verb, env, _payload(harness_id, tmp_path))


@pytest.mark.parametrize("harness_id", ("claude-code", "codex", "cursor"))
def test_user_hook_runs_outside_any_project(tmp_path, harness_id):
    env = _environment(harness_id, tmp_path)
    assert not should_skip_config_duplicate("PreToolUse", env, _payload(harness_id, tmp_path))


def test_codex_finds_project_hooks_from_a_subfolder(tmp_path):
    _write_project(tmp_path, "codex")
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "src" / "pkg"
    nested.mkdir(parents=True)
    env = _environment("codex", tmp_path)
    assert should_skip_config_duplicate("Stop", env, _payload("codex", nested))


def test_codex_search_stops_at_the_repository_root(tmp_path):
    _write_project(tmp_path, "codex")
    repo = tmp_path / "other-repo"
    (repo / ".git").mkdir(parents=True)
    env = _environment("codex", repo)
    assert not should_skip_config_duplicate("Stop", env, _payload("codex", repo))


def test_older_project_render_without_owner_marker_still_owns(tmp_path):
    settings = tmp_path / ".claude/settings.json"
    settings.parent.mkdir()
    old = "/bin/sh -c 'env YOKE_ROOT=\"$PWD\" yoke hook evaluate Stop'"
    settings.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": old}]}]}}))
    env = _environment("claude-code", tmp_path)
    assert should_skip_config_duplicate("Stop", env, _payload("claude-code", tmp_path))
    assert not should_skip_config_duplicate("SessionStart", env, _payload("claude-code", tmp_path))


def test_a_machine_wide_entry_in_a_project_file_owns_nothing(tmp_path):
    settings = tmp_path / ".claude/settings.json"
    settings.parent.mkdir()
    user = "env YOKE_HOOK_CONFIG_OWNER=claude-user yoke hook evaluate Stop"
    settings.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": user}]}]}}))
    env = _environment("claude-code", tmp_path)
    assert not should_skip_config_duplicate("Stop", env, _payload("claude-code", tmp_path))


def test_a_project_file_the_harness_rejects_owns_nothing(tmp_path):
    settings = tmp_path / ".claude/settings.json"
    settings.parent.mkdir()
    flat = {"type": "command", "command": "yoke hook evaluate Stop"}
    settings.write_text(json.dumps({"hooks": {"Stop": [flat]}}))
    env = _environment("claude-code", tmp_path)
    assert not should_skip_config_duplicate("Stop", env, _payload("claude-code", tmp_path))


def test_cursor_imported_user_claude_hook_steps_aside_for_cursor_owner(tmp_path):
    home = tmp_path / "home"
    (home / ".cursor").mkdir(parents=True)
    owned = "env YOKE_HOOK_CONFIG_OWNER=cursor-user yoke hook evaluate"
    hooks = {
        "sessionStart": [{"command": f"{owned} SessionStart"}],
        "beforeShellExecution": [{"command": f"{owned} PreToolUse"}],
    }
    (home / ".cursor/hooks.json").write_text(json.dumps({"version": 1, "hooks": hooks}))
    env = {
        "YOKE_HOOK_CONFIG_OWNER": "claude-user",
        "CURSOR_PROJECT_DIR": str(tmp_path / "workspace"),
        "HOME": str(home),
    }
    assert should_skip_config_duplicate("SessionStart", env, CURSOR_PAYLOAD)
    # Cursor fires the imported user-level Claude hook beside its own shell
    # hook (measured on cursor-agent 2026.10.16-e3cb207), so it steps aside.
    assert should_skip_config_duplicate("PreToolUse", env, CURSOR_PAYLOAD)
    # An event Cursor's own config does not own still runs once.
    assert not should_skip_config_duplicate("Stop", env, CURSOR_PAYLOAD)


def test_skipped_claude_user_hook_prints_nothing_and_never_evaluates(
    monkeypatch, tmp_path, capsys
):
    _write_project(tmp_path, "claude-code")
    for key, value in _environment("claude-code", tmp_path).items():
        monkeypatch.setenv(key, value)
    for key in ("CURSOR_PROJECT_DIR", "CURSOR_TRANSCRIPT_PATH", "CURSOR_INVOKED_AS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(_payload("claude-code", tmp_path)))
    monkeypatch.setattr(
        "yoke_cli.transport.https.resolve_https_connection",
        lambda: (_ for _ in ()).throw(AssertionError("step-aside must not evaluate")),
    )

    assert cli_main(["hook", "evaluate", "PreToolUse"]) == 0
    assert capsys.readouterr().out == ""
