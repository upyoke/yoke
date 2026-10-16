"""The SessionStart duties that run on the machine hosting the harness.

``yoke_harness.hooks.session_lifecycle.session_lifecycle`` is what the
relay's local subset runs for ``yoke_core.hooks.session_dispatch``: it
fast-forwards the project's main checkout and, for the Claude family,
persists ``YOKE_SESSION_ID`` into ``CLAUDE_ENV_FILE``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest
from yoke_contracts.hook_runner.project_scope import HookProjectScope
from yoke_contracts.session_identity import AMBIENT_ENV_VARS

from yoke_harness.hooks import session_lifecycle as lifecycle

_SID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in AMBIENT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / "claude.env"
    monkeypatch.setenv("CLAUDE_ENV_FILE", str(path))
    return path


@pytest.fixture
def lane(tmp_path: Path) -> tuple[Path, Path]:
    """A primary checkout and a linked worktree of it."""
    main = tmp_path / "main"
    main.mkdir()

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(main), *args], check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git(
        "-c",
        "user.email=t@e",
        "-c",
        "user.name=t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "init",
    )
    worktree = tmp_path / "lane"
    git("worktree", "add", "-q", str(worktree), "-b", "lane")
    return main.resolve(), worktree.resolve()


def _run(event: str, payload: dict, executor: str = "claude-code", project_id=7):
    with (
        mock.patch.object(
            lifecycle,
            "resolve_hook_project_scope",
            return_value=HookProjectScope(project_id=project_id),
        ),
        mock.patch.object(lifecycle, "sync_session_main_checkout") as sync,
    ):
        lifecycle.session_lifecycle(event, payload, executor)
    return sync


def test_session_start_persists_session_id_once(env_file: Path, tmp_path: Path) -> None:
    payload = {"session_id": _SID, "cwd": str(tmp_path)}

    _run("SessionStart", payload)
    _run("SessionStart", payload)

    assert env_file.read_text(encoding="utf-8") == f"export YOKE_SESSION_ID={_SID}\n"


def test_session_start_syncs_the_payload_cwds_main_checkout(
    env_file: Path, lane: tuple[Path, Path]
) -> None:
    main, worktree = lane

    sync = _run("SessionStart", {"session_id": _SID, "cwd": str(worktree)})

    sync.assert_called_once_with(str(main))


@pytest.mark.parametrize("event", ["UserPromptSubmit", "Stop", "SessionEnd"])
def test_other_events_do_nothing(env_file: Path, tmp_path: Path, event: str) -> None:
    sync = _run(event, {"session_id": _SID, "cwd": str(tmp_path)})

    sync.assert_not_called()
    assert not env_file.exists()


def test_non_project_session_does_nothing(env_file: Path, tmp_path: Path) -> None:
    sync = _run(
        "SessionStart", {"session_id": _SID, "cwd": str(tmp_path)}, project_id=None
    )

    sync.assert_not_called()
    assert not env_file.exists()


@pytest.mark.parametrize("executor", ["codex", "cursor"])
def test_env_file_is_only_for_the_claude_family(
    env_file: Path, tmp_path: Path, executor: str
) -> None:
    sync = _run("SessionStart", {"session_id": _SID, "cwd": str(tmp_path)}, executor)

    sync.assert_called_once()
    assert not env_file.exists()


def test_env_file_session_id_falls_back_to_env_file_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in AMBIENT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(
        "CLAUDE_ENV_FILE", str(tmp_path / "session-env" / _SID / "hook.sh")
    )

    assert lifecycle.env_file_session_id({}) == _SID


def test_unsynced_checkout_warns_on_stderr(capsys: pytest.CaptureFixture) -> None:
    freshness = mock.Mock(needs_attention=True, note="local commits ahead")
    with mock.patch.object(lifecycle, "refresh_base_branch", return_value=freshness):
        advisory = lifecycle.sync_session_main_checkout("/repo")

    assert advisory == "main checkout not fast-forwarded: local commits ahead"
    assert (
        f"WARNING: {lifecycle.NOT_SYNCED_MARKER}: {advisory}" in capsys.readouterr().err
    )
