"""Deleted shell directories refuse commands and leave harness hooks open."""

import io
import json
import os
from contextlib import contextmanager

import pytest

from yoke_cli.main import main
from yoke_contracts.machine_config.selection import checkout_connection
from yoke_contracts.working_directory import WorkingDirectoryMissing, current_directory


@contextmanager
def deleted_directory(tmp_path):
    original = os.open(".", os.O_RDONLY)
    folder = tmp_path / "removed"
    folder.mkdir()
    os.chdir(folder)
    folder.rmdir()
    try:
        yield
    finally:
        os.fchdir(original)
        os.close(original)


def test_current_directory_returns_process_directory():
    assert current_directory() == os.getcwd()


@pytest.mark.posix_only(reason="Windows cannot delete an in-use working directory")
def test_checkout_connection_names_deleted_directory(tmp_path):
    with deleted_directory(tmp_path):
        with pytest.raises(WorkingDirectoryMissing, match="working_directory_missing"):
            checkout_connection({})


@pytest.mark.posix_only(reason="Windows cannot delete an in-use working directory")
def test_command_refuses_deleted_directory(tmp_path, capsys):
    with deleted_directory(tmp_path):
        code = main(["items", "get", "X-1", "status"])
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "working_directory_missing" in captured.err
    assert "cd to the project checkout and retry" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize("executor", ["claude-code", "codex", "cursor"])
@pytest.mark.posix_only(reason="Windows cannot delete an in-use working directory")
def test_hook_allows_deleted_directory(tmp_path, monkeypatch, capsys, executor):
    monkeypatch.setenv("YOKE_EXECUTOR", executor)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("YOKE_HOOKS_OFF", raising=False)
    monkeypatch.delenv("YOKE_HOOK_CONFIG_OWNER", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    with deleted_directory(tmp_path):
        code = main(["hook", "evaluate", "PreToolUse"])
    captured = capsys.readouterr()
    assert code == 0
    reply = json.loads(captured.out)
    if executor == "cursor":
        assert reply["permission"] == "allow"
    else:
        assert "hookSpecificOutput" not in reply
        assert "working_directory_missing" in reply["systemMessage"]
    assert "working_directory_missing" in captured.err
    assert "Traceback" not in captured.err


def _hook_env(monkeypatch, executor):
    monkeypatch.setenv("YOKE_EXECUTOR", executor)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("YOKE_HOOKS_OFF", raising=False)
    monkeypatch.delenv("YOKE_HOOK_CONFIG_OWNER", raising=False)


@pytest.mark.parametrize("executor", ["claude-code", "codex", "cursor"])
def test_hook_names_removed_payload_folder(tmp_path, monkeypatch, capsys, executor):
    """The hook child's own folder survives; the session folder is gone."""
    _hook_env(monkeypatch, executor)
    removed = tmp_path / "removed"
    payload = json.dumps({"cwd": str(removed), "session_id": "s-1"})
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    monkeypatch.setattr(
        "yoke_cli.commands.adapters.hooks._dispatch_hook",
        lambda *a: pytest.fail("a removed session folder must not reach dispatch"),
    )
    code = main(["hook", "evaluate", "PreToolUse"])
    captured = capsys.readouterr()
    assert code == 0
    reply = json.loads(captured.out)
    if executor == "cursor":
        assert reply["permission"] == "allow"
    else:
        assert "hookSpecificOutput" not in reply
        assert "working_directory_missing" in reply["systemMessage"]
    assert "working_directory_missing" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    "payload",
    [{}, {"cwd": 7}, {"cwd": "relative/gone"}, {"cwd": ""}, "not json"],
)
def test_hook_dispatches_without_authoritative_payload_folder(
    monkeypatch, capsys, payload
):
    _hook_env(monkeypatch, "claude-code")
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr("sys.stdin", io.StringIO(raw))
    monkeypatch.setattr(
        "yoke_cli.commands.adapters.hooks._dispatch_hook",
        lambda *a: print('{"dispatched": true}') or 0,
    )
    code = main(["hook", "evaluate", "PreToolUse"])
    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out) == {"dispatched": True}
    assert "working_directory_missing" not in captured.err


@pytest.mark.parametrize("bypass", ["hooks_off", "disabled_folder"])
def test_hook_bypass_policy_precedes_payload_folder(
    tmp_path, monkeypatch, capsys, bypass
):
    _hook_env(monkeypatch, "claude-code")
    removed = tmp_path / "removed"
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(removed)})))
    if bypass == "hooks_off":
        monkeypatch.setenv("YOKE_HOOKS_OFF", "1")
    else:
        monkeypatch.setattr(
            "yoke_contracts.hook_runner.folder_scope.folder_scope",
            lambda raw: "disabled",
        )
    code = main(["hook", "evaluate", "PreToolUse"])
    captured = capsys.readouterr()
    assert code == 0
    assert "working_directory_missing" not in captured.out + captured.err
