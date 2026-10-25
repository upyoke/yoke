"""Install, idempotence, preservation, refusal and removal of machine-wide hooks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_contracts.harness_machine_hooks import HARNESS_MACHINE_HOOKS
from yoke_harness.hooks import machine_hooks
from yoke_harness.hooks.machine_hooks import (
    ensure_machine_hooks,
    ensure_machine_hooks_for_executor,
    remove_machine_hooks,
)
from yoke_harness.hooks.machine_hooks_inspect import inspect_machine_hooks

HARNESSES = tuple(HARNESS_MACHINE_HOOKS)


def _env(tmp_path: Path, *homes: str) -> dict[str, str]:
    for home in homes:
        (tmp_path / home).mkdir(parents=True, exist_ok=True)
    return {"HOME": str(tmp_path)}


def _config(tmp_path: Path, harness_id: str) -> Path:
    return HARNESS_MACHINE_HOOKS[harness_id].user_config_path({"HOME": str(tmp_path)})


def _commands(document: dict) -> list[str]:
    from yoke_contracts.harness_machine_hooks import entry_commands

    return [
        command
        for entries in document["hooks"].values()
        for entry in entries
        for command in entry_commands(entry)
    ]


def _operator_hooks(harness_id: str) -> dict:
    if harness_id == "cursor":
        return {"stop": [{"command": "echo mine"}]}
    return {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}


@pytest.mark.parametrize("harness_id", HARNESSES)
def test_install_writes_light_set_once_and_keeps_operator_entries(tmp_path, harness_id):
    spec = HARNESS_MACHINE_HOOKS[harness_id]
    env = _env(tmp_path, spec.home.removeprefix("~/"))
    path = _config(tmp_path, harness_id)
    document = {"hooks": _operator_hooks(harness_id)}
    if harness_id == "claude-code":
        document["model"] = "opus"
    if harness_id == "cursor":
        document["version"] = 1
    path.write_text(json.dumps(document))

    [result] = ensure_machine_hooks([harness_id], env)
    assert result.outcome == "installed", result.line()
    written = json.loads(path.read_text())
    assert set(written["hooks"]) >= {event.native_event for event in spec.events}
    owned = [c for c in _commands(written) if f"YOKE_HOOK_CONFIG_OWNER={spec.config_owner}" in c]
    assert len(owned) == len(spec.events)
    assert "echo mine" in _commands(written)
    if harness_id == "claude-code":
        assert written["model"] == "opus"
    # Yoke's entries go last so a person's handler positions never move.
    stop = spec.native_events_for("Stop")[0]
    assert _commands({"hooks": {stop: written["hooks"][stop][:1]}}) == ["echo mine"]

    [again] = ensure_machine_hooks([harness_id], env)
    assert again.outcome == "unchanged"


@pytest.mark.parametrize("harness_id", HARNESSES)
def test_missing_home_is_not_installed_and_creates_nothing(tmp_path, harness_id):
    [result] = ensure_machine_hooks([harness_id], {"HOME": str(tmp_path)})
    spec = HARNESS_MACHINE_HOOKS[harness_id]
    assert result.outcome == machine_hooks.not_installed(spec)
    assert not spec.home_path({"HOME": str(tmp_path)}).exists()


def test_codex_absent_reports_codex_not_installed(tmp_path):
    [result] = ensure_machine_hooks(["codex"], {"HOME": str(tmp_path)})
    assert result.outcome == "codex_not_installed"
    assert not (tmp_path / ".codex").exists()


@pytest.mark.parametrize("harness_id", HARNESSES)
def test_malformed_config_is_never_overwritten(tmp_path, harness_id):
    spec = HARNESS_MACHINE_HOOKS[harness_id]
    env = _env(tmp_path, spec.home.removeprefix("~/"))
    path = _config(tmp_path, harness_id)
    path.write_text("{not json")

    [result] = ensure_machine_hooks([harness_id], env)
    assert result.outcome == "machine_hooks_config_malformed"
    assert "fix or move the file, then run `yoke setup` again" in result.detail
    assert path.read_text() == "{not json"
    [state] = inspect_machine_hooks(env)
    assert state.outcome == "malformed"


def test_retired_cursor_entries_are_replaced(tmp_path):
    env = _env(tmp_path, ".cursor")
    path = _config(tmp_path, "cursor")
    retired = "env YOKE_CURSOR_LIFECYCLE_ROOT=1 yoke hook evaluate Stop"
    canary = "/bin/zsh -lc 'echo >> /tmp/yoke-cursor-stop-canary.log'"
    path.write_text(
        json.dumps({"version": 1, "hooks": {"stop": [{"command": retired}, {"command": canary}]}})
    )

    ensure_machine_hooks(["cursor"], env)
    commands = _commands(json.loads(path.read_text()))
    assert not any("YOKE_CURSOR_LIFECYCLE_ROOT" in c or "canary" in c for c in commands)
    installed = len(HARNESS_MACHINE_HOOKS["cursor"].events)
    assert sum("YOKE_HOOK_CONFIG_OWNER=cursor-user " in c for c in commands) == installed


@pytest.mark.parametrize("harness_id", HARNESSES)
def test_remove_keeps_operator_entries_and_deletes_a_file_left_empty(tmp_path, harness_id):
    spec = HARNESS_MACHINE_HOOKS[harness_id]
    env = _env(tmp_path, spec.home.removeprefix("~/"))
    path = _config(tmp_path, harness_id)
    ensure_machine_hooks([harness_id], env)

    results = {r.harness_id: r for r in remove_machine_hooks(env)}
    assert results[harness_id].outcome == "deleted"
    assert not path.exists()

    document = {"hooks": _operator_hooks(harness_id)}
    path.write_text(json.dumps(document))
    ensure_machine_hooks([harness_id], env)
    results = {r.harness_id: r for r in remove_machine_hooks(env)}
    assert results[harness_id].outcome == "removed"
    assert json.loads(path.read_text())["hooks"] == document["hooks"]
    results = {r.harness_id: r for r in remove_machine_hooks(env)}
    assert results[harness_id].outcome == "absent"


def test_inspect_reports_missing_stale_and_installed(tmp_path):
    env = _env(tmp_path, ".claude")
    assert [r.outcome for r in inspect_machine_hooks(env)] == ["missing"]
    ensure_machine_hooks(["claude-code"], env)
    assert [r.outcome for r in inspect_machine_hooks(env)] == ["installed"]
    path = _config(tmp_path, "claude-code")
    document = json.loads(path.read_text())
    document["hooks"]["Stop"][0]["hooks"][0]["command"] += " --stale"
    path.write_text(json.dumps(document))
    assert [r.outcome for r in inspect_machine_hooks(env)] == ["stale"]


def test_self_heal_rewrites_only_on_difference_and_never_raises(tmp_path, monkeypatch, capsys):
    claude = tmp_path / "harness-home" / ".claude"  # the conftest-isolated home
    claude.mkdir(parents=True)
    path = claude / "settings.json"

    ensure_machine_hooks_for_executor("claude-code", hook="SessionStart")
    assert path.is_file()
    stamp = path.stat().st_mtime_ns
    ensure_machine_hooks_for_executor("claude-code", hook="SessionStart")
    assert path.stat().st_mtime_ns == stamp

    path.write_text("{broken")
    ensure_machine_hooks_for_executor("claude-code", hook="Stop")
    assert path.read_text() == "{broken"
    assert "yoke (Stop): " in capsys.readouterr().err

    monkeypatch.setattr(machine_hooks, "ensure_harness", lambda *_a, **_k: 1 / 0)
    ensure_machine_hooks_for_executor("claude-code", hook="Stop")
    assert "machine-wide hooks were not checked" in capsys.readouterr().err


def test_cursor_user_commands_avoid_the_bytes_its_hook_loader_mishandles():
    from yoke_contracts.cursor_hook_command_bytes import (
        CURSOR_HOOK_COMMAND_FORBIDDEN_SEQUENCES,
    )
    from yoke_harness.hooks.machine_hooks_render import render_user_hook_entries

    rendered = render_user_hook_entries(HARNESS_MACHINE_HOOKS["cursor"])
    for entries in rendered.values():
        for entry in entries:
            for sequence in CURSOR_HOOK_COMMAND_FORBIDDEN_SEQUENCES:
                assert sequence not in entry["command"], (sequence, entry["command"])


def test_current_entries_are_never_reformatted_or_reordered(tmp_path):
    env = _env(tmp_path, ".codex")
    path = _config(tmp_path, "codex")
    ensure_machine_hooks(["codex"], env)
    document = json.loads(path.read_text())
    document["hooks"]["Stop"].append({"hooks": [{"type": "command", "command": "echo later"}]})
    path.write_text(json.dumps(document, separators=(",", ":")))  # a harness's own formatting
    text = path.read_text()

    [result] = ensure_machine_hooks(["codex"], env)
    assert result.outcome == "unchanged"
    assert path.read_text() == text
    assert [r.outcome for r in inspect_machine_hooks(env)] == ["installed"]
