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
from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters.hook_config_dedup import should_skip_config_duplicate
from yoke_cli.main import main as cli_main
from yoke_core.domain.agents_render_hooks import (
    render_claude_hooks_block,
    render_codex_hooks_block,
    render_cursor_hooks_block,
)

CURSOR_PAYLOAD = '{"session_id":"c-1","conversation_id":"c-1"}'


def _native_windows(monkeypatch) -> None:
    """Native Windows as the launchability check sees it: no ``/bin/sh``.

    Only the check's own module sees ``nt``, so pathlib in this process keeps
    its POSIX paths; ``yoke`` resolves the way ``yoke.cmd`` does on PATH.
    """
    from yoke_contracts import hook_shell_command as shell

    monkeypatch.setattr(shell, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        shell,
        "shutil",
        SimpleNamespace(which=lambda name: name if name == "yoke" else None),
    )


def _write_project(root: Path, harness_id: str) -> None:
    """The real project render for one harness, as setup installs it."""
    if harness_id == "claude-code":
        path, document = (
            root / ".claude/settings.json",
            {"hooks": render_claude_hooks_block()},
        )
    elif harness_id == "codex":
        path, document = (
            root / ".codex/hooks.json",
            {"hooks": render_codex_hooks_block()},
        )
    else:
        path, document = root / ".cursor/hooks.json", render_cursor_hooks_block()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def _environment(harness_id: str, root: Path) -> dict[str, str]:
    owner = {
        "claude-code": "claude-user",
        "codex": "codex-user",
        "cursor": "cursor-user",
    }
    env = {"YOKE_HOOK_CONFIG_OWNER": owner[harness_id], "HOME": str(root / "home")}
    if harness_id == "claude-code":
        env["CLAUDE_PROJECT_DIR"] = str(root)
    if harness_id == "cursor":
        env["CURSOR_PROJECT_DIR"] = str(root)
    return env


def _payload(harness_id: str, root: Path) -> str:
    if harness_id == "cursor":
        return json.dumps(
            {"session_id": "c-1", "conversation_id": "c-1", "cwd": str(root)}
        )
    return json.dumps({"session_id": "s-1", "cwd": str(root)})


@pytest.mark.parametrize("harness_id", ("claude-code", "codex", "cursor"))
@pytest.mark.parametrize(
    "verb", ("SessionStart", "UserPromptSubmit", "PreToolUse", "Stop")
)
def test_user_hook_steps_aside_inside_a_project(tmp_path, harness_id, verb):
    _write_project(tmp_path, harness_id)
    env = _environment(harness_id, tmp_path)
    assert should_skip_config_duplicate(verb, env, _payload(harness_id, tmp_path))


@pytest.mark.parametrize("harness_id", ("claude-code", "codex", "cursor"))
def test_user_hook_runs_outside_any_project(tmp_path, harness_id):
    env = _environment(harness_id, tmp_path)
    assert not should_skip_config_duplicate(
        "PreToolUse", env, _payload(harness_id, tmp_path)
    )


def test_cursor_project_runs_one_post_tool_use_evaluation(tmp_path):
    """The project and user configs both fire postToolUse; only one evaluates."""
    _write_project(tmp_path, "cursor")
    payload = _payload("cursor", tmp_path)
    user = _environment("cursor", tmp_path)
    project = {**user, "YOKE_HOOK_CONFIG_OWNER": "cursor-project"}
    evaluations = [
        not should_skip_config_duplicate("PostToolUse", env, payload)
        for env in (user, project)
    ]
    assert evaluations == [False, True]


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
    settings.write_text(
        json.dumps(
            {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": old}]}]}}
        )
    )
    env = _environment("claude-code", tmp_path)
    assert should_skip_config_duplicate("Stop", env, _payload("claude-code", tmp_path))
    assert not should_skip_config_duplicate(
        "SessionStart", env, _payload("claude-code", tmp_path)
    )


def test_a_machine_wide_entry_in_a_project_file_owns_nothing(tmp_path):
    settings = tmp_path / ".claude/settings.json"
    settings.parent.mkdir()
    user = "env YOKE_HOOK_CONFIG_OWNER=claude-user yoke hook evaluate Stop"
    settings.write_text(
        json.dumps(
            {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": user}]}]}}
        )
    )
    env = _environment("claude-code", tmp_path)
    assert not should_skip_config_duplicate(
        "Stop", env, _payload("claude-code", tmp_path)
    )


def test_a_project_file_the_harness_rejects_owns_nothing(tmp_path):
    settings = tmp_path / ".claude/settings.json"
    settings.parent.mkdir()
    flat = {"type": "command", "command": "yoke hook evaluate Stop"}
    settings.write_text(json.dumps({"hooks": {"Stop": [flat]}}))
    env = _environment("claude-code", tmp_path)
    assert not should_skip_config_duplicate(
        "Stop", env, _payload("claude-code", tmp_path)
    )


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


@pytest.mark.parametrize(
    "harness,project_owner,user_owner,config_rel",
    [
        ("claude-code", "claude", "claude-user", ".claude/settings.json"),
        ("cursor", "cursor-project", "cursor-user", ".cursor/hooks.json"),
    ],
)
@pytest.mark.parametrize("machine_entry", [False, True])
def test_encoded_windows_hook_ownership(
    monkeypatch,
    tmp_path,
    harness,
    project_owner,
    user_owner,
    config_rel,
    machine_entry,
):
    from yoke_contracts.hook_shell_command import windows_hook_command

    _native_windows(monkeypatch)
    owner = user_owner if machine_entry else project_owner
    handler = {"command": windows_hook_command(harness, "Stop", owner)}
    if harness == "cursor":
        document = {"version": 1, "hooks": {"stop": [handler]}}
    else:
        handler["type"] = "command"
        document = {"hooks": {"Stop": [{"hooks": [handler]}]}}
    path = tmp_path / config_rel
    path.parent.mkdir()
    path.write_text(json.dumps(document))
    assert should_skip_config_duplicate(
        "Stop",
        _environment(harness, tmp_path),
        _payload(harness, tmp_path),
    ) is (not machine_entry)


_PROJECT_OWNER = {"claude-code": "claude", "cursor": "cursor-project"}
_NATIVE = {
    ("claude-code", "SessionStart"): "SessionStart",
    ("claude-code", "PostToolUse"): "PostToolUse",
    ("cursor", "SessionStart"): "sessionStart",
    ("cursor", "PostToolUse"): "postToolUse",
}


def _write_windows_project(root: Path, harness_id: str, verb: str) -> None:
    """A project render made for native Windows: a bare startable ``yoke``."""
    from yoke_contracts.hook_shell_command import windows_hook_command

    handler = {
        "command": windows_hook_command(harness_id, verb, _PROJECT_OWNER[harness_id])
    }
    native = _NATIVE[(harness_id, verb)]
    if harness_id == "cursor":
        path, document = (
            root / ".cursor/hooks.json",
            {"version": 1, "hooks": {native: [handler]}},
        )
    else:
        handler["type"] = "command"
        path = root / ".claude/settings.json"
        document = {"hooks": {native: [{"hooks": [handler]}]}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


@pytest.mark.parametrize("harness_id", ("claude-code", "cursor"))
@pytest.mark.parametrize("verb", ("SessionStart", "PostToolUse"))
@pytest.mark.parametrize("project_startable", (False, True))
def test_native_windows_runs_one_hook_whether_or_not_the_project_hook_starts(
    monkeypatch, tmp_path, harness_id, verb, project_startable
):
    """An unstartable ``/bin/sh`` project hook never silences the machine hook."""
    from yoke_contracts.harness_machine_hooks import HARNESS_MACHINE_HOOKS
    from yoke_contracts.hook_shell_command import hook_command_start_problem

    _native_windows(monkeypatch)
    if project_startable:
        _write_windows_project(tmp_path, harness_id, verb)
    else:
        _write_project(tmp_path, harness_id)  # The tracked /bin/sh render.
    document = json.loads(
        next((tmp_path / rel).read_text() for rel in (
            ".claude/settings.json", ".cursor/hooks.json"
        ) if (tmp_path / rel).is_file())
    )
    entries = document["hooks"][_NATIVE[(harness_id, verb)]]
    handlers = [h for entry in entries for h in entry.get("hooks", [entry])]
    project_starts = all(not hook_command_start_problem(h) for h in handlers)
    assert project_starts is project_startable

    payload = _payload(harness_id, tmp_path)
    machine_env = _environment(harness_id, tmp_path)
    project_env = {**machine_env, "YOKE_HOOK_CONFIG_OWNER": _PROJECT_OWNER[harness_id]}
    machine_installed = bool(
        HARNESS_MACHINE_HOOKS[harness_id].native_events_for(verb)
    )
    runs = []
    if machine_installed and not should_skip_config_duplicate(verb, machine_env, payload):
        runs.append("machine")
    if project_starts and not should_skip_config_duplicate(verb, project_env, payload):
        runs.append("project")
    if project_startable:
        assert runs == ["project"]
    else:
        # Claude installs no machine PostToolUse, so nothing else owns it.
        assert runs == (["machine"] if machine_installed else [])
