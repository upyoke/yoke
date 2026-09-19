"""A path the repository ignores is not the source the guard protects.

The strategy render is the worked case: `yoke strategy render` writes
`.yoke/strategy/<SLUG>.md` in the main checkout and `yoke strategy
ingest` reads it back, so the documented recipe cannot run in a lane.
Denying it taught the escape token as routine. Tracked source in the
same checkout must still be refused, which is what the second test pins.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)
from runtime.api.fixtures.machine_config_test import register_machine_checkout
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import lint_lane_main_write

IGNORED_RENDER = ".yoke/strategy/RELEASES.md"
TRACKED_SOURCE = "packages/yoke-core/src/yoke_core/domain/example_module.py"
SESSION = "sid-lane"
ITEM_ID = 2014


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def repo(tmp_path):
    """A real checkout: the ignore rules are read from git, not guessed."""
    repo_path = tmp_path / "repo"
    (repo_path / ".worktrees").mkdir(parents=True)
    _git(repo_path, "init", "--quiet")
    (repo_path / ".gitignore").write_text(".yoke/strategy/\n", encoding="utf-8")
    tracked = repo_path / TRACKED_SOURCE
    tracked.parent.mkdir(parents=True, exist_ok=True)
    tracked.write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo_path, "add", ".gitignore", TRACKED_SOURCE)
    return repo_path


def _git(repo_path: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo_path), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _seed_lane(conn, repo) -> Path:
    register_machine_checkout(
        Path(repo).parent / "machine-config", Path(repo), project_id=1
    )
    seed_item(
        conn,
        item_id=ITEM_ID,
        branch=f"YOK-{ITEM_ID}",
        status="implementing",
        repo_path=repo,
    )
    seed_item_claim(conn, SESSION, item_id=ITEM_ID)
    worktree = repo / ".worktrees" / f"YOK-{ITEM_ID}"
    worktree.mkdir(parents=True, exist_ok=True)
    return worktree


def _write(repo: Path, relative: str) -> dict:
    return {
        "session_id": SESSION,
        "tool_name": "Write",
        "cwd": str(repo),
        "tool_input": {"file_path": str(repo / relative), "content": "body\n"},
    }


def test_an_ignored_render_target_is_allowed_on_main(conn, repo) -> None:
    _seed_lane(conn, repo)

    verdict = lint_lane_main_write.evaluate_pre_tool_use(
        _write(repo, IGNORED_RENDER)
    )

    assert verdict.allow is True


def test_tracked_source_in_the_same_checkout_is_still_denied(conn, repo) -> None:
    worktree = _seed_lane(conn, repo)

    with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
        verdict = lint_lane_main_write.evaluate_pre_tool_use(
            _write(repo, TRACKED_SOURCE)
        )

    assert verdict.allow is False
    assert str(worktree / TRACKED_SOURCE) in verdict.reason
