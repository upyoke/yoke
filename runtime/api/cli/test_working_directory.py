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


def test_checkout_connection_names_deleted_directory(tmp_path):
    with deleted_directory(tmp_path):
        with pytest.raises(WorkingDirectoryMissing, match="working_directory_missing"):
            checkout_connection({})


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
