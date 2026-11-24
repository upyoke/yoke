"""``yoke hook evaluate --harness`` sets the context the POSIX env prefix sets."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from yoke_cli.commands.adapters.hook_invocation_context import (
    apply_hook_invocation_context,
)


@pytest.fixture(autouse=True)
def _restore_cwd():
    before = os.getcwd()
    yield
    os.chdir(before)


@pytest.mark.windows
def test_posix_form_without_harness_changes_nothing(tmp_path) -> None:
    environ = {"YOKE_ROOT": "kept"}
    apply_hook_invocation_context(None, "PreToolUse", None, environ)
    assert environ == {"YOKE_ROOT": "kept"}


@pytest.mark.windows
def test_codex_root_falls_back_to_the_hook_cwd(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    environ: dict[str, str] = {}
    apply_hook_invocation_context("codex", "Stop", "codex-user", environ)
    assert environ == {
        "YOKE_ROOT": str(tmp_path),
        "YOKE_EXECUTOR": "codex",
        "YOKE_PROVIDER": "openai",
        "YOKE_HOOK_CONFIG_OWNER": "codex-user",
    }


@pytest.mark.windows
@pytest.mark.parametrize(
    ("verb", "owner"), [("Stop", "cursor-project"), ("PreToolUse", "cursor-user")]
)
def test_cursor_walk_peels_a_deleted_lane_and_enters_its_checkout(
    tmp_path, monkeypatch, verb, owner
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.chdir(tmp_path)
    environ = {"CURSOR_PROJECT_DIR": str(checkout / ".worktrees" / "gone" / "sub")}
    apply_hook_invocation_context("cursor", verb, owner, environ)
    assert environ["YOKE_ROOT"] == str(tmp_path)  # The existing cwd wins first.

    environ = {
        "YOKE_ROOT": str(checkout / ".claude" / "worktrees" / "gone"),
        "CURSOR_PROJECT_DIR": "",
    }
    missing = tmp_path / "missing"
    missing.mkdir()
    os.chdir(missing)
    real_getcwd = os.getcwd
    if os.name == "nt":  # Windows refuses to remove a process's cwd.

        def deleted_cwd() -> str:
            raise FileNotFoundError(str(missing))

        monkeypatch.setattr(os, "getcwd", deleted_cwd)
    else:
        missing.rmdir()
    try:
        apply_hook_invocation_context("cursor", verb, owner, environ)
    finally:  # Fixture teardown reads the real cwd.
        monkeypatch.setattr(os, "getcwd", real_getcwd)
    assert Path(environ["YOKE_ROOT"]) == checkout
    assert Path(real_getcwd()) == checkout.resolve()
    assert environ["YOKE_EXECUTOR"] == "cursor"


@pytest.mark.windows
def test_cursor_project_tool_hook_keeps_its_project_root(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    environ = {"CURSOR_PROJECT_DIR": "C:/ws"}
    apply_hook_invocation_context("cursor", "PreToolUse", "cursor-project", environ)
    assert environ["YOKE_ROOT"] == "C:/ws"
    assert Path(os.getcwd()) == tmp_path.resolve()


@pytest.mark.windows
def test_dispatch_applies_context_before_the_duplicate_check(
    tmp_path, monkeypatch
) -> None:
    from yoke_cli.commands.adapters import hooks

    seen: dict[str, str] = {}

    def skip(event_name, environment, stdin_data):
        seen.update(owner=environment.get("YOKE_HOOK_CONFIG_OWNER", ""))
        seen.update(root=environment.get("YOKE_ROOT", ""))
        return True

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("YOKE_HOOK_CONFIG_OWNER", raising=False)
    monkeypatch.setenv("YOKE_ROOT", "replaced")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(hooks, "should_skip_config_duplicate", skip)
    code = hooks._dispatch_hook(
        ["Stop", "--harness", "claude-code", "--config-owner", "claude-user"], "{}"
    )
    assert code == 0
    assert seen == {"owner": "claude-user", "root": str(tmp_path)}


@pytest.mark.windows
def test_dispatch_refuses_an_unknown_harness(capsys) -> None:
    from yoke_cli.commands.adapters import hooks

    assert hooks._dispatch_hook(["Stop", "--harness", "vim"], "{}") == 2
    assert "Usage: yoke hook evaluate" in capsys.readouterr().err
