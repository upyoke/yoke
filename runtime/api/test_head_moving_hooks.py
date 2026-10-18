"""Every git operation that moves HEAD records the lane head.

``item_worktrees.commit_sha`` names the commit a lane offers. A commit fires
``post-commit``, but a fast-forward merge, a pull, a rebase and a branch
switch create no commit, so before the post-merge, post-rewrite and
post-checkout shims existed the recorded head silently fell behind the
lane. These tests run real git against the real installed shims, then drive
the recordings they trigger through the real ``yoke git <hook>`` commands.
"""

from __future__ import annotations

import os
import subprocess
from contextlib import nullcontext
from pathlib import Path
from typing import Any, List, Tuple

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_cli.commands import git_hook
from yoke_cli.main import main as cli_main
from yoke_cli.project_install.git_hooks import BootstrapResult, install_git_hooks
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
)
from yoke_contracts.git_hook_markers import HEAD_RECORDING_GIT_HOOKS
from yoke_core.domain.handlers import project_snapshot_sync as handler
from yoke_core.domain.item_worktrees import record_item_worktree
from yoke_core.domain.workflow_behavior import LANE_IMPLEMENTATION

# Stands in for the machine-installed launcher: logs which hook git fired,
# with what arguments, and where HEAD stood when it fired.
_FAKE_LAUNCHER = """#!/bin/sh
hook="$2"
shift 2
printf '%s\\t%s\\t%s\\n' "$hook" "$(git rev-parse HEAD)" "$*" >> "{log}"
"""


def _git(repo: Path, *args: str, env: dict | None = None) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    ).stdout.strip()


def _hooked_repo(tmp_path: Path) -> Tuple[Path, dict, Path]:
    repo = tmp_path / "lane"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    install_git_hooks(repo, BootstrapResult())
    log = tmp_path / "hooks.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    launcher = bin_dir / "yoke"
    launcher.write_text(_FAKE_LAUNCHER.format(log=log), encoding="utf-8")
    launcher.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    return repo, env, log


def _commit(repo: Path, env: dict, name: str) -> None:
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", name, env=env)
    _git(repo, "commit", "-q", "-m", name, env=env)


def _fired(log: Path) -> List[Tuple[str, str, List[str]]]:
    """Head-recording invocations since the last read, then clear the log."""
    if not log.exists():
        return []
    rows = []
    for line in log.read_text(encoding="utf-8").splitlines():
        hook, head, args = line.split("\t")
        if hook in HEAD_RECORDING_GIT_HOOKS:
            rows.append((hook, head, args.split()))
    log.unlink()
    return rows


def _recorded_heads(monkeypatch, fired) -> List[str]:
    """Run each fired hook's real command; return the heads it records."""
    recorded: List[str] = []
    for hook, head, args in fired:
        calls: List[List[str]] = []
        monkeypatch.setattr(git_hook, "project_snapshot_sync", calls.append)
        assert cli_main(["git", hook, *args]) == 0
        if calls:
            assert calls == [["--hook", hook, "--head-only"]]
            recorded.append(head)
    return recorded


def test_every_head_move_records_the_new_head(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(git_hook.HEAD_RECORDING_SKIP_ENV, raising=False)
    monkeypatch.delenv(git_hook.PROJECT_ID_ENV, raising=False)
    repo, env, log = _hooked_repo(tmp_path)
    _commit(repo, env, "seed")
    _git(repo, "branch", "lane", env=env)

    def moved(operation: str) -> None:
        recorded = _recorded_heads(monkeypatch, _fired(log))
        head = _git(repo, "rev-parse", "HEAD")
        assert recorded, f"{operation} recorded nothing"
        assert recorded[-1] == head, f"{operation} recorded a stale head"

    _commit(repo, env, "main-1")
    moved("commit")
    _git(repo, "checkout", "-q", "lane", env=env)
    moved("branch checkout")
    _git(repo, "merge", "-q", "--ff-only", "main", env=env)
    moved("fast-forward merge")
    _git(repo, "checkout", "-q", "main", env=env)
    _commit(repo, env, "main-2")
    _git(repo, "checkout", "-q", "lane", env=env)
    _fired(log)
    _git(repo, "rebase", "-q", "main", env=env)
    moved("fast-forward rebase")
    _commit(repo, env, "lane-1")
    _git(repo, "checkout", "-q", "main", env=env)
    _commit(repo, env, "main-3")
    _git(repo, "checkout", "-q", "lane", env=env)
    _fired(log)
    _git(repo, "rebase", "-q", "main", env=env)
    moved("rebase")
    _git(repo, "checkout", "-q", "main", env=env)
    _commit(repo, env, "main-4")
    _git(repo, "checkout", "-q", "lane", env=env)
    _fired(log)
    _git(repo, "merge", "-q", "--no-edit", "main", env=env)
    moved("merge commit")
    _git(repo, "commit", "-q", "--amend", "--no-edit", env=env)
    moved("amend")


def test_moves_that_change_nothing_record_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(git_hook.HEAD_RECORDING_SKIP_ENV, raising=False)
    repo, env, log = _hooked_repo(tmp_path)
    _commit(repo, env, "seed")
    _fired(log)
    (repo / "seed").write_text("edited", encoding="utf-8")
    _git(repo, "checkout", "--", "seed", env=env)
    _git(repo, "checkout", "-q", "-b", "same-commit", env=env)

    fired = _fired(log)

    assert fired, "git fired no post-checkout at all"
    assert _recorded_heads(monkeypatch, fired) == []


def test_gate_rebase_replay_records_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(git_hook.HEAD_RECORDING_SKIP_ENV, "1")
    for hook in HEAD_RECORDING_GIT_HOOKS:
        calls: List[List[str]] = []
        monkeypatch.setattr(git_hook, "project_snapshot_sync", calls.append)
        assert cli_main(["git", hook, "a", "b", "1"]) == 0
        assert calls == []


def _bridge(**kwargs: Any) -> FunctionCallResponse:
    outcome = handler.handle_project_snapshot_sync(
        FunctionCallRequest(
            function=kwargs["function_id"],
            actor=ActorContext(session_id="test-session"),
            target=kwargs["target"],
            payload=kwargs["payload"],
        )
    )
    return FunctionCallResponse(
        success=outcome.primary_success,
        function=kwargs["function_id"],
        version="v1",
        result=outcome.result_payload or {},
        error=outcome.error,
    )


@pytest.mark.parametrize("operation", ["merge", "rebase"])
def test_fast_forward_updates_the_recorded_lane_head(
    tmp_path, test_db, monkeypatch, operation
) -> None:
    repo = tmp_path / "lane"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "core.hooksPath", "/dev/null")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T",
        "GIT_AUTHOR_EMAIL": "t@e",
        "GIT_COMMITTER_NAME": "T",
        "GIT_COMMITTER_EMAIL": "t@e",
    }
    _commit(repo, env, "seed")
    _git(repo, "branch", "lane", env=env)
    _commit(repo, env, "main-1")
    _git(repo, "checkout", "-q", "lane", env=env)
    before = _git(repo, "rev-parse", "HEAD")
    insert_item(test_db, id=4253, workflow_id="issue")
    record_item_worktree(
        test_db,
        item_id=4253,
        branch="lane",
        path=str(repo.resolve()),
        lane_role=LANE_IMPLEMENTATION,
    )
    test_db.commit()
    chunked = "yoke_cli.commands.adapters.project_snapshot_chunked"
    monkeypatch.setattr(f"{chunked}.call_dispatcher", _bridge)
    monkeypatch.setattr(f"{chunked}.ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect",
        lambda *_a, **_k: nullcontext(test_db),
    )
    monkeypatch.setenv(git_hook.PROJECT_ID_ENV, "yoke")
    monkeypatch.delenv(git_hook.HEAD_RECORDING_SKIP_ENV, raising=False)
    monkeypatch.chdir(repo)

    if operation == "merge":
        _git(repo, "merge", "-q", "--ff-only", "main", env=env)
        assert cli_main(["git", "post-merge", "0"]) == 0
    else:
        _git(repo, "rebase", "-q", "main", env=env)
        assert cli_main(["git", "post-checkout", before, "x", "1"]) == 0

    after = _git(repo, "rev-parse", "HEAD")
    assert after != before
    row = test_db.execute(
        "SELECT commit_sha FROM item_worktrees WHERE item_id = 4253"
    ).fetchone()
    assert row[0] == after
