"""Declared setup failures stay visible without preventing lane creation."""

import sys

import pytest

from yoke_core.domain import worktree_deps


@pytest.fixture(autouse=True)
def isolated_install(monkeypatch):
    monkeypatch.setattr(worktree_deps, "resolve_playwright_cache", lambda *_: None)


def test_unreadable_declaration_does_not_autodetect(tmp_path, monkeypatch, capsys):
    def unreadable(*_):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(worktree_deps, "get_setup_command", unreadable)
    monkeypatch.setattr(worktree_deps, "detect_deps", lambda *_: pytest.fail("autodetected"))
    result = {}
    assert worktree_deps.install_worktree_deps(str(tmp_path), "42", setup_result=result) == 1
    assert result == {"status": "failed", "command": None}
    output = capsys.readouterr().err
    assert "SETUP-COMMAND-UNREADABLE" in output
    assert "connection refused" in output
    assert "Recovery:" in output and "rerun lane prepare" in output


def test_setup_failure_keeps_command_output(tmp_path, monkeypatch, capfd):
    command = f"{sys.executable} -c \"import sys; print('missing locked wheel'); sys.exit(7)\""
    monkeypatch.setattr(worktree_deps, "get_setup_command", lambda *_: command)
    result = {}
    assert worktree_deps.install_worktree_deps(str(tmp_path), "42", setup_result=result) == 1
    assert result == {"status": "failed", "command": command}
    captured = capfd.readouterr()
    assert "missing locked wheel" in captured.err
    assert captured.out == ""
    assert "SETUP-COMMAND-FAILED" in captured.err
    assert "exited 7" in captured.err and str(tmp_path) in captured.err
    assert "--base '<current setup_command settings JSON>'" in captured.err


def test_undeclared_setup_reports_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(worktree_deps, "get_setup_command", lambda *_: None)
    result = {}
    assert worktree_deps.install_worktree_deps(str(tmp_path), "42", setup_result=result) == 0
    assert result == {"status": "skipped", "command": None}


def test_prepare_envelope_reports_setup():
    from yoke_core.domain.worktree_preflight_outcome import WorktreePreflightOutcome

    result = {"status": "ran", "command": "./setup"}
    assert WorktreePreflightOutcome(setup_command=result).to_envelope()["setup_command"] == result


def test_successful_setup_keeps_json_stdout_parseable(tmp_path, monkeypatch, capfd):
    import json
    from yoke_core.domain.worktree_preflight_outcome import WorktreePreflightOutcome

    command = f"{sys.executable} -c \"print('environment ready')\""
    monkeypatch.setattr(worktree_deps, "get_setup_command", lambda *_: command)
    result = {}
    assert worktree_deps.install_worktree_deps(str(tmp_path), "42", setup_result=result) == 0
    print(json.dumps(WorktreePreflightOutcome(setup_command=result).to_envelope()))
    captured = capfd.readouterr()
    assert json.loads(captured.out)["setup_command"] == {"status": "ran", "command": command}
    assert "environment ready" in captured.err


@pytest.mark.parametrize("settings", ['{"command":42}', '[]', 'invalid'])
def test_invalid_declaration_is_unreadable(tmp_path, monkeypatch, capsys, settings):
    from yoke_contracts.api.function_call import FunctionCallResponse

    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        lambda **kwargs: FunctionCallResponse(
            success=True, function=kwargs["function_id"], version="v1",
            result={"settings_json": settings},
        ),
    )
    result = {}
    assert worktree_deps.install_worktree_deps(str(tmp_path), "42", setup_result=result) == 1
    assert result["status"] == "failed"
    assert "SETUP-COMMAND-UNREADABLE" in capsys.readouterr().err
