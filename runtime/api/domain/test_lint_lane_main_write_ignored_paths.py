"""A path the repository ignores is not the source the guard protects.

The strategy render is the worked case: `yoke strategy render` writes
`.yoke/strategy/<SLUG>.md` in the main checkout and `yoke strategy
ingest` reads it back, so the documented recipe cannot run in a lane.
Denying it taught the escape token as routine. Tracked source in the
same checkout must still be refused, which is what the second test pins.

The checkout lives on the client, so the ignore answer and the live lanes
arrive as the client's write-targets fact; the authority runs no git.
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
from yoke_contracts.hook_runner.client_facts import WRITE_TARGETS_KEY
from yoke_harness.hooks.client_write_targets import write_targets_fact

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
    repo_path = tmp_path.resolve() / "repo"
    (repo_path / ".worktrees").mkdir(parents=True)
    _git(repo_path, "init", "--quiet")
    (repo_path / ".gitignore").write_text(
        ".yoke/strategy/\n.worktrees/\n", encoding="utf-8"
    )
    tracked = repo_path / TRACKED_SOURCE
    tracked.parent.mkdir(parents=True, exist_ok=True)
    tracked.write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo_path, "add", ".gitignore", TRACKED_SOURCE)
    _git(
        repo_path,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "seed",
    )
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
    _git(repo, "worktree", "add", "--quiet", str(worktree), "-b", f"YOK-{ITEM_ID}")
    return worktree


def _write(repo: Path, relative: str) -> dict:
    payload = {
        "session_id": SESSION,
        "tool_name": "Write",
        "cwd": str(repo),
        "tool_input": {"file_path": str(repo / relative), "content": "body\n"},
    }
    # The client answers for its own checkout before the payload leaves it.
    return {**payload, **write_targets_fact(payload)}


def _refuse_subprocess(*_args, **_kwargs):
    raise AssertionError("the authority ran a subprocess against its own disk")


def _evaluate_on_empty_machine(payload: dict, monkeypatch):
    """Evaluate with no git available, so only the client fact can answer."""
    monkeypatch.setattr(subprocess, "run", _refuse_subprocess)
    monkeypatch.setattr(subprocess, "Popen", _refuse_subprocess)
    with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
        return lint_lane_main_write.evaluate_pre_tool_use(payload)


def test_the_client_fact_reports_ignore_status_and_live_lanes(conn, repo) -> None:
    worktree = _seed_lane(conn, repo)

    ignored = _write(repo, IGNORED_RENDER)
    tracked = _write(repo, TRACKED_SOURCE)

    raw_ignored = str(repo / IGNORED_RENDER)
    raw_tracked = str(repo / TRACKED_SOURCE)
    ignored_fact = ignored[WRITE_TARGETS_KEY]["value"]
    tracked_fact = tracked[WRITE_TARGETS_KEY]["value"]
    assert ignored_fact["paths"][raw_ignored]["ignored"] is True
    assert tracked_fact["paths"][raw_tracked]["ignored"] is False
    assert str(worktree) in tracked_fact["worktrees"]


def test_an_ignored_render_target_is_allowed_on_main(conn, repo) -> None:
    _seed_lane(conn, repo)

    verdict = lint_lane_main_write.evaluate_pre_tool_use(_write(repo, IGNORED_RENDER))

    assert verdict.allow is True


def test_tracked_source_in_the_same_checkout_is_still_denied(conn, repo) -> None:
    worktree = _seed_lane(conn, repo)

    with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
        verdict = lint_lane_main_write.evaluate_pre_tool_use(
            _write(repo, TRACKED_SOURCE)
        )

    assert verdict.allow is False
    assert str(worktree / TRACKED_SOURCE) in verdict.reason


@pytest.mark.parametrize(
    ("relative", "allowed"), [(IGNORED_RENDER, True), (TRACKED_SOURCE, False)]
)
def test_the_verdict_needs_no_git_on_the_evaluating_machine(
    conn, repo, monkeypatch, relative, allowed
) -> None:
    _seed_lane(conn, repo)
    payload = _write(repo, relative)

    verdict = _evaluate_on_empty_machine(payload, monkeypatch)

    assert verdict.allow is allowed


def test_without_the_client_fact_an_ignored_path_counts_as_tracked(conn, repo) -> None:
    _seed_lane(conn, repo)
    payload = _write(repo, IGNORED_RENDER)
    payload.pop(WRITE_TARGETS_KEY)

    with mock.patch.object(lint_lane_main_write, "emit_denied", return_value=None):
        verdict = lint_lane_main_write.evaluate_pre_tool_use(payload)

    assert verdict.allow is False
