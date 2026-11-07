"""Folder privacy is enforced before any transport, observer or hook dispatch."""

from __future__ import annotations

import io
import json
import subprocess
import sys

import pytest

from yoke_contracts.hook_runner import folder_scope as scope
from yoke_contracts.machine_config import runtime as config


@pytest.fixture
def folder_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    monkeypatch.delenv("YOKE_SESSION_LAUNCH_CONTEXT", raising=False)
    document = {"connections": {"one": {}, "two": {}}, "connection_projects": {}}
    monkeypatch.setattr(config, "load_config", lambda *a: document)
    return document


def test_registration_on_any_connection_and_next_hook(tmp_path, folder_config):
    assert scope.folder_scope() == "unregistered"
    folder_config["connection_projects"]["two"] = [{"checkout": str(tmp_path), "project_id": 7}]
    assert scope.folder_scope() == "registered"


@pytest.mark.parametrize("key", ["cwd", "workspace", "project_dir", "workspace_roots"])
def test_disabled_workspace_facts_and_subfolders(tmp_path, folder_config, key):
    child = tmp_path / "disabled" / "child"
    child.mkdir(parents=True)
    folder_config["disabled_folders"] = [str(child.parent)]
    value = [str(child)] if key == "workspace_roots" else str(child)
    assert scope.folder_scope(json.dumps({key: value})) == "disabled"
    assert scope.folder_scope(path=child) == "disabled"
    assert scope.folder_scope(path=tmp_path / "disabled-other") == "unregistered"


@pytest.mark.parametrize("variable", ["YOKE_ENV", "YOKE_SESSION_LAUNCH_CONTEXT"])
def test_explicit_routing_never_overrides_disabled(tmp_path, folder_config, monkeypatch, variable):
    monkeypatch.setenv(variable, "explicit")
    assert scope.folder_scope() == "registered"
    folder_config["disabled_folders"] = [str(tmp_path)]
    assert scope.folder_scope() == "disabled"


def test_git_lane_and_nested_independent_repository(tmp_path, folder_config):
    root = tmp_path / "repo"
    root.mkdir()
    def git(path, *args):
        subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)
    git(root, "init", "-b", "main")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "--allow-empty", "-m", "initial")
    folder_config["connection_projects"]["one"] = [{"checkout": str(root), "project_id": 7}]
    lane = tmp_path / "lane"
    git(root, "worktree", "add", "-b", "work", str(lane))
    assert scope.folder_scope(path=lane) == "registered"
    nested = root / "independent"
    nested.mkdir()
    git(nested, "init", "-b", "main")
    assert scope.folder_scope(path=nested) == "unregistered"


@pytest.mark.parametrize("executor", ["claude-code", "codex", "cursor"])
@pytest.mark.parametrize("event", ["SessionStart", "UserPromptSubmit", "PreToolUse", "Stop"])
def test_disabled_returns_before_dispatch(tmp_path, folder_config, monkeypatch, capsys, executor, event):
    from yoke_cli.commands.adapters import hooks
    from yoke_contracts.hook_runner.degraded import plain_allow_stdout

    folder_config["disabled_folders"] = [str(tmp_path)]
    monkeypatch.setenv("YOKE_EXECUTOR", executor)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(tmp_path)})))
    monkeypatch.setattr(hooks, "_dispatch_hook", lambda *a: pytest.fail("dispatched disabled hook"))
    assert hooks.hook_evaluate([event]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == plain_allow_stdout(event, executor)


@pytest.mark.parametrize("executor", ["claude-code", "codex", "cursor"])
@pytest.mark.parametrize("transport", ["https", "local-postgres", "local-only"])
def test_unregistered_skips_every_transport_and_telemetry(
    tmp_path, folder_config, monkeypatch, capsys, executor, transport,
):
    from yoke_cli.commands.adapters import hook_inprocess as entry
    from yoke_cli.transport import https
    from yoke_harness.hooks import identity, relay

    folder_config["connections"]["one"]["transport"] = transport
    folder_config["active_env"] = "one"
    monkeypatch.setattr(identity, "detect_executor", lambda: executor)
    monkeypatch.setattr(entry, "_session_orientation", lambda *a, **kw: "local orientation")
    monkeypatch.setattr(entry, "_touch_detached_resume", lambda: None)
    monkeypatch.setattr(https, "resolve_https_connection", lambda: pytest.fail("connection selected"))
    monkeypatch.setattr(entry, "_active_local_universe", lambda: pytest.fail("Postgres selected"))
    monkeypatch.setattr(relay, "relay_hook_event", lambda *a, **kw: pytest.fail("network relay"))
    def local(event, **kwargs):
        print(kwargs["extra_context"])
        return 0
    monkeypatch.setattr(relay, "evaluate_hook_event", local)
    assert entry.evaluate_inprocess(
        "PreToolUse", json.dumps({"cwd": str(tmp_path)}), dry_run=False,
        cursor_invocation=executor == "cursor", on_complete=lambda: pytest.fail("telemetry"),
    ) == 0
    assert "local orientation" in capsys.readouterr().out


def test_folder_commands_persist_and_restore(tmp_path, monkeypatch, capsys):
    from yoke_cli.commands.folder import folder_disable, folder_enable

    selected = tmp_path / "machine" / "config.json"
    monkeypatch.setattr(config, "config_path", lambda: selected)
    monkeypatch.setattr(config, "load_config", lambda: json.loads(selected.read_text()) if selected.exists() else {})
    # Exercise the real atomic, owner-private config writer in a disposable home.
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(selected.parent))
    assert folder_disable([str(tmp_path)]) == 0
    assert json.loads(selected.read_text())["disabled_folders"] == [str(tmp_path)]
    assert folder_enable([str(tmp_path)]) == 0
    assert json.loads(selected.read_text())["disabled_folders"] == []
    assert "Hooks enabled" in capsys.readouterr().out


def test_outside_orientation_and_machine_guards_are_local(tmp_path, folder_config, monkeypatch, capsys):
    from yoke_cli.commands.adapters import hook_inprocess as entry
    from yoke_cli.transport import https
    from yoke_harness.hooks import identity, machine_hooks, relay, local_subset
    from yoke_core.domain.global_orientation import render_global_orientation

    monkeypatch.setattr(identity, "detect_executor", lambda: "cursor")
    monkeypatch.setattr(entry, "_touch_detached_resume", lambda: None)
    monkeypatch.setattr(https, "resolve_https_connection", lambda: pytest.fail("connection selected"))
    monkeypatch.setattr(machine_hooks, "ensure_machine_hooks_for_executor", lambda *a, **k: None)
    monkeypatch.setattr(relay, "evaluate_local_subset", local_subset.evaluate_local_subset)
    monkeypatch.setattr(relay, "detect_executor", lambda: "cursor")
    monkeypatch.setattr(relay, "stamp_hook_input", lambda payload, raw, *a: (raw, None))
    monkeypatch.setattr(entry, "_session_orientation", lambda *a, **kw: render_global_orientation(
        "local-session", tmp_path, setup_lines=[],
    ))
    assert entry.evaluate_inprocess(
        "SessionStart", json.dumps({"cwd": str(tmp_path), "conversation_id": "local-session"}),
        dry_run=False, cursor_invocation=True,
    ) == 0
    assert "outside every Yoke project" in capsys.readouterr().out
    assert entry.evaluate_inprocess(
        "PreToolUse", json.dumps({"cwd": str(tmp_path), "tool_name": "Bash", "shell": "zsh",
            "tool_input": {"command": "cat ./missing/*.py"}}),
        dry_run=False, cursor_invocation=True,
    ) == 0
    assert "deny" in capsys.readouterr().out


def test_disabled_status_and_doctor_skip_session_lookup(tmp_path, folder_config, monkeypatch):
    from yoke_cli.config.status_session import attach_session_state
    from yoke_core.engines import doctor_install
    from types import SimpleNamespace

    folder_config["disabled_folders"] = [str(tmp_path)]
    report = attach_session_state({"repo_root": str(tmp_path)})
    assert report["session"]["presence"] == "no hook session: folder is disabled"
    monkeypatch.setattr(doctor_install, "build_actor", lambda: pytest.fail("session lookup"))
    rows = []
    doctor_install.hc_session_hook_registration(None, None, SimpleNamespace(record=lambda *a: rows.append(a)))
    assert rows[0][2] == doctor_install.NOT_APPLICABLE
    assert "disabled" in rows[0][3]
