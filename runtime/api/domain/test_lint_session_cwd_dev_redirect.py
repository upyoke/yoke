"""/dev family redirects are not filesystem writes."""

from __future__ import annotations

from yoke_contracts.cursor_session_map import CURSOR_CONVERSATION_ENV_VAR
from yoke_contracts.session_identity import AMBIENT_ENV_VARS
from yoke_core.domain.lint_lane_main_write_classify import is_write_operation
from yoke_core.domain.lint_session_cwd import evaluate_pre_tool_use
from yoke_core.domain.lint_session_cwd_identity import FAILURE_CLASS as IDENTITY_FAILURE_CLASS
from yoke_core.domain.lint_session_cwd_target_extract import (
    glued_file_redirect_target,
    _split_redirect_targets,
)


def _bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _clear_ambient(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    for name in (*AMBIENT_ENV_VARS, CURSOR_CONVERSATION_ENV_VAR):
        monkeypatch.delenv(name, raising=False)


def test_glued_dev_null_is_not_a_file_redirect_target() -> None:
    assert glued_file_redirect_target("2>/dev/null") is None
    assert glued_file_redirect_target(">/dev/null") is None
    assert glued_file_redirect_target(">/tmp/out") == "/tmp/out"


def test_split_redirect_skips_dev_family() -> None:
    _clean, targets = _split_redirect_targets(["cmd", "2>", "/dev/null"])
    assert targets == []
    _clean, targets = _split_redirect_targets(["echo", "hi", ">", "/tmp/out"])
    assert targets == ["/tmp/out"]


def test_dev_null_pipeline_is_not_a_write() -> None:
    command = "yoke items get X 2>/dev/null | python3 -c 'print(1)'"
    assert is_write_operation("Bash", _bash(command)) is False


def test_dev_null_and_fd_dup_is_not_a_write() -> None:
    assert is_write_operation("Bash", _bash("cmd >/dev/null 2>&1")) is False


def test_tmp_redirect_and_write_tool_remain_writes() -> None:
    assert is_write_operation("Bash", _bash("echo hi > /tmp/out")) is True
    assert is_write_operation("Write", {"tool_name": "Write"}) is True


def test_unidentified_dev_null_pipeline_is_allowed(monkeypatch, tmp_path) -> None:
    _clear_ambient(monkeypatch, tmp_path)
    verdict = evaluate_pre_tool_use(_bash(
        "yoke items get X 2>/dev/null | python3 -c 'print(1)'"
    ))
    assert verdict.allow is True


def test_unidentified_real_write_still_denies_identity(monkeypatch, tmp_path) -> None:
    _clear_ambient(monkeypatch, tmp_path)
    verdict = evaluate_pre_tool_use(_bash("echo hi > /tmp/out"))
    assert verdict.allow is False
    assert verdict.failure_class == IDENTITY_FAILURE_CLASS

