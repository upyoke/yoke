"""Preparation fetches upstream before a lane, a resume, or laneless work.

The project here is an external one — its own bare remote, its own clone,
and a default branch named something other than ``main`` — so the branch
the preflight uses is the one the project declares rather than a constant.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.api import (
    service_client_structured_api_adapter as structured_api_adapter,
)
from yoke_core.domain import repo_upstream_freshness as freshness
from yoke_core.domain import worktree_create
from yoke_core.domain import worktree_preflight as wp
from yoke_core.domain import worktree_preflight_steps as steps
from yoke_core.domain import worktree_preflight_upstream as gate

DEFAULT_BRANCH = "trunk"
ITEM_ID = 9101


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


def _commit(repo: Path, name: str, body: str) -> str:
    (repo / name).write_text(body)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", f"add {name}")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def project(tmp_path: Path) -> SimpleNamespace:
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    subprocess.run(
        ["git", "init", "-q", "--bare", f"--initial-branch={DEFAULT_BRANCH}", str(origin)],
        check=True,
    )
    subprocess.run(
        ["git", "init", "-q", f"--initial-branch={DEFAULT_BRANCH}", str(seed)], check=True
    )
    _git(seed, "config", "user.email", "test@example.com")
    _git(seed, "config", "user.name", "Test")
    _commit(seed, "README.md", "seed\n")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "-q", "-u", "origin", DEFAULT_BRANCH)
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "clone", "-q", str(origin), str(checkout)], check=True)
    _git(checkout, "config", "user.email", "test@example.com")
    _git(checkout, "config", "user.name", "Test")
    return SimpleNamespace(root=checkout, seed=seed, origin=origin)


def _advance_remote(project: SimpleNamespace, name: str = "upstream.txt") -> str:
    sha = _commit(project.seed, name, "from the remote\n")
    _git(project.seed, "push", "-q", "origin", DEFAULT_BRANCH)
    return sha


def _patch_preflight(
    monkeypatch, *, lane_path: str = "", recorded_lane=None, created: bool = True
):
    """Stand in for the control-plane steps the freshness step sits between."""
    # The gate reads the branch the item's project declares, so the item
    # detail has to carry one for any of this to be exercised at all.
    item = {
        "id": ITEM_ID,
        "public_ref": f"YOK-{ITEM_ID}",
        "blocked": False,
        "project": {"default_branch": DEFAULT_BRANCH},
        "workflow": {"policies": {"worktrees": "single_implementation_lane"}},
    }
    monkeypatch.setattr(
        structured_api_adapter,
        "call_dispatcher",
        lambda **_kwargs: SimpleNamespace(success=True, result={"item": item}, error=None),
    )
    monkeypatch.setattr(
        wp, "resolve_item_branch_and_lane", lambda _i: (f"YOK-{ITEM_ID}", recorded_lane)
    )
    monkeypatch.setattr(wp, "claim_work", lambda _i: (True, "(already owned)"))
    monkeypatch.setattr(wp, "activate_path_claims", lambda _i: (True, "", []))
    monkeypatch.setattr(
        wp,
        "evaluate_dirty_main_for_item",
        lambda *_a, **_k: SimpleNamespace(
            blocked=False,
            kind="",
            narrative="",
            needed_paths=(),
            source_root_prefixes=(),
            warning_note="",
        ),
    )
    passed: dict = {}

    def _create(**kwargs):
        passed.update(kwargs)
        return worktree_create.CreateWorktreeResult(
            path=lane_path, branch=f"YOK-{ITEM_ID}", created=created
        )

    monkeypatch.setattr(worktree_create, "create_worktree", _create)
    return passed


def _run(project: SimpleNamespace, *, no_worktree: bool = False):
    return wp.run_preflight(
        item_id=ITEM_ID,
        repo_root=str(project.root),
        session_id="sess",
        actual_cwd=str(project.root),
        no_worktree=no_worktree,
    )


def test_new_lane_is_cut_from_the_fetched_upstream_revision(project, monkeypatch):
    remote_sha = _advance_remote(project)
    created = _patch_preflight(monkeypatch, lane_path=str(project.root / "lane"))

    outcome = _run(project)

    assert outcome.ok is True
    assert created["base_branch"] == remote_sha
    assert f"upstream:{freshness.STATE_FAST_FORWARDED}" in outcome.actions_taken
    assert _git(project.root, "rev-parse", DEFAULT_BRANCH) == remote_sha


def test_resumed_lane_reports_freshness_without_touching_the_lane(
    project, monkeypatch
):
    _advance_remote(project)
    _git(project.root, "branch", f"YOK-{ITEM_ID}")
    lane = project.root / ".worktrees" / f"YOK-{ITEM_ID}"
    _git(project.root, "worktree", "add", "-q", str(lane), f"YOK-{ITEM_ID}")
    lane_head = _git(lane, "rev-parse", "HEAD")
    (lane / "in-progress.txt").write_text("half-finished\n")
    _patch_preflight(
        monkeypatch, lane_path=str(lane), recorded_lane=str(lane), created=False
    )

    outcome = _run(project)

    assert outcome.ok is True
    assert "worktree:reused" in outcome.actions_taken
    assert any(freshness.NOTE_PREFIX in note for note in outcome.notes)
    # The lane keeps its own head and its uncommitted work.
    assert _git(lane, "rev-parse", "HEAD") == lane_head
    assert (lane / "in-progress.txt").read_text() == "half-finished\n"


def test_laneless_work_refuses_on_a_branch_that_could_not_be_updated(
    project, monkeypatch
):
    _advance_remote(project, name="README.md")
    (project.root / "README.md").write_text("uncommitted\n")
    _patch_preflight(monkeypatch)

    outcome = _run(project, no_worktree=True)

    assert outcome.ok is False
    assert outcome.block_kind == steps.BLOCK_UPSTREAM_STALE
    assert "commit or stash" in outcome.narrative
    assert (project.root / "README.md").read_text() == "uncommitted\n"


def test_laneless_work_refuses_on_a_diverged_branch(project, monkeypatch):
    _advance_remote(project)
    _commit(project.root, "local.txt", "mine\n")
    _patch_preflight(monkeypatch)

    outcome = _run(project, no_worktree=True)

    assert outcome.ok is False
    assert outcome.block_kind == steps.BLOCK_UPSTREAM_STALE
    assert "rebase" in outcome.narrative


def test_laneless_work_proceeds_once_the_branch_is_current(project, monkeypatch):
    remote_sha = _advance_remote(project)
    _patch_preflight(monkeypatch)

    outcome = _run(project, no_worktree=True)

    assert outcome.ok is True
    assert "worktree:skipped" in outcome.actions_taken
    assert _git(project.root, "rev-parse", DEFAULT_BRANCH) == remote_sha


def test_local_commits_keep_the_lane_on_the_local_branch(project, monkeypatch):
    _advance_remote(project)
    local_sha = _commit(project.root, "local.txt", "mine\n")
    passed = _patch_preflight(monkeypatch, lane_path=str(project.root / "lane"))

    outcome = _run(project)

    assert outcome.ok is True
    assert passed["base_branch"] == DEFAULT_BRANCH
    assert f"upstream:{freshness.STATE_DIVERGED}" in outcome.actions_taken
    assert _git(project.root, "rev-parse", DEFAULT_BRANCH) == local_sha


def test_a_lane_refuses_when_the_remote_cannot_be_read(project, monkeypatch):
    _git(project.root, "remote", "set-url", "origin", str(project.root / "gone.git"))
    passed = _patch_preflight(monkeypatch, lane_path=str(project.root / "lane"))

    outcome = _run(project)

    assert outcome.ok is False
    assert outcome.block_kind == steps.BLOCK_UPSTREAM_UNVERIFIED
    assert "could not fetch" in outcome.narrative
    # No lane was cut from an unverified base.
    assert passed == {}


def test_laneless_work_refuses_when_the_remote_cannot_be_read(project, monkeypatch):
    _git(project.root, "remote", "set-url", "origin", str(project.root / "gone.git"))
    _patch_preflight(monkeypatch)

    outcome = _run(project, no_worktree=True)

    assert outcome.ok is False
    assert outcome.block_kind == steps.BLOCK_UPSTREAM_UNVERIFIED


def test_a_second_preparation_reads_the_remote_again(project, monkeypatch):
    """A long-running process prepares repeatedly; each reads the remote."""
    _patch_preflight(monkeypatch, lane_path=str(project.root / "lane"))
    first = _run(project)
    assert first.ok is True
    assert f"upstream:{freshness.STATE_CURRENT}" in first.actions_taken

    remote_sha = _advance_remote(project)
    passed = _patch_preflight(monkeypatch, lane_path=str(project.root / "lane"))
    second = _run(project)

    assert f"upstream:{freshness.STATE_FAST_FORWARDED}" in second.actions_taken
    assert passed["base_branch"] == remote_sha


def test_an_item_with_no_project_gates_on_nothing(project, monkeypatch):
    """The floor case: no declared branch, so no repository to gate on."""
    _advance_remote(project)
    fetched: list[str] = []
    monkeypatch.setattr(
        freshness.upstream_git,
        "fetch_branch",
        lambda *a, **k: fetched.append("fetch"),
    )

    outcome = gate.gate_upstream_for_preparation(
        str(project.root), {}, no_worktree=True
    )

    assert outcome.freshness is None
    assert outcome.block_kind == ""
    # The checkout the caller stands in is not the item's project, so it is
    # never read at all.
    assert fetched == []
