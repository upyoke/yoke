"""Native Windows keeps the machine hook when a project hook cannot start.

A tracked ``/bin/sh`` project command cannot start on native Windows, so it
owns nothing and the machine-wide hook keeps the event; a project command
that starts there still owns it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli.commands.adapters.hook_config_dedup import should_skip_config_duplicate
from runtime.api.cli.machine_hook_dedup_test_support import (
    environment as _environment,
    native_windows as _native_windows,
    payload as _payload,
    write_project as _write_project,
    yoke_on_path,
)


@pytest.fixture(autouse=True)
def _yoke_on_path(monkeypatch) -> None:
    yoke_on_path(monkeypatch)


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
        _write_project(tmp_path, harness_id, native=False)  # Tracked /bin/sh.
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
