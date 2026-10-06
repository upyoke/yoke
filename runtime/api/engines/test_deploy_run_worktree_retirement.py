"""A finished deploy run's pinned driver worktree is reclaimed; a live one is not."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.engines import deploy_run_worktree_retirement as retirement
from yoke_core.engines.deploy_run_worktree_naming import (
    deploy_run_worktree_paths,
    driver_worktree_path,
    run_id_for_driver_worktree,
)
from yoke_core.engines.deploy_run_worktree_retirement import (
    LANE_BLOCKED,
    LANE_RETIRABLE,
    LANE_RETIRED,
    LANE_RUN_OPEN,
    assess_deploy_run_worktrees,
    retire_terminal_deploy_run_worktrees,
)


_AUTHOR = (
    "-c",
    "user.name=deploy-worktree-test",
    "-c",
    "user.email=deploy-worktree-test@example.invalid",
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Fixture Git command failed ({result.returncode}): {result.args!r}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result


def _run_git(args: list[str], *, cwd=None, capture: bool = False, **_kw):
    """The run_git shape every worktree engine takes: no leading ``git``."""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )


def _repo(root: Path) -> Path:
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    (root / "seed").write_text("seed", encoding="utf-8")
    # In the base commit, so a worktree pinned at any later revision inherits
    # it — which is what a real checkout looks like to a driver.
    (root / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, *_AUTHOR, "commit", "-q", "-m", "seed", "--no-gpg-sign")
    return root


def _driver_worktree(repo: Path, run_id: str) -> Path:
    path = driver_worktree_path(repo, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "--detach", str(path), "HEAD")
    return path


@pytest.fixture(autouse=True)
def _no_declared_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answer the project's declared-disposable-paths read locally.

    It is a best-effort control-plane lookup; letting it reach a real relay
    makes every test here wait out a retry backoff to learn nothing.
    """
    monkeypatch.setattr(
        retirement, "declared_disposable_roots", lambda _root: frozenset()
    )


@pytest.fixture
def statuses(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Answer the run-status read from a dict instead of a control plane."""
    table: dict[str, str] = {}

    def fake_status(run_id: str) -> tuple[str, str]:
        if run_id not in table:
            return "", "no such run"
        return table[run_id], ""

    monkeypatch.setattr(retirement, "_run_status", fake_status)
    return table


def test_terminal_run_worktree_is_retired(
    tmp_path: Path, statuses: dict[str, str]
) -> None:
    repo = _repo(tmp_path / "repo")
    path = _driver_worktree(repo, "run-20260101-001")
    statuses["run-20260101-001"] = "succeeded"

    verdicts = retire_terminal_deploy_run_worktrees(repo_root=repo, run_git=_run_git)

    assert [lane.state for lane in verdicts] == [LANE_RETIRED]
    assert not path.exists()
    assert deploy_run_worktree_paths(_run_git, repo) == []


@pytest.mark.parametrize("status", ["succeeded", "failed", "cancelled"])
def test_every_terminal_status_is_retired(
    tmp_path: Path, statuses: dict[str, str], status: str
) -> None:
    repo = _repo(tmp_path / "repo")
    path = _driver_worktree(repo, "run-20260101-001")
    statuses["run-20260101-001"] = status

    retire_terminal_deploy_run_worktrees(repo_root=repo, run_git=_run_git)

    assert not path.exists()


@pytest.mark.parametrize("status", ["created", "executing"])
def test_live_run_worktree_is_kept(
    tmp_path: Path, statuses: dict[str, str], status: str
) -> None:
    repo = _repo(tmp_path / "repo")
    path = _driver_worktree(repo, "run-20260101-002")
    statuses["run-20260101-002"] = status

    verdicts = retire_terminal_deploy_run_worktrees(repo_root=repo, run_git=_run_git)

    assert [lane.state for lane in verdicts] == [LANE_RUN_OPEN]
    assert verdicts[0].run_is_open
    assert status in verdicts[0].reason
    assert path.is_dir()


def test_dirty_deploy_worktree_is_kept_with_a_named_reason(
    tmp_path: Path, statuses: dict[str, str]
) -> None:
    repo = _repo(tmp_path / "repo")
    path = _driver_worktree(repo, "run-20260101-003")
    statuses["run-20260101-003"] = "succeeded"
    (path / "operator-scratch.txt").write_text("keep me", encoding="utf-8")

    verdicts = retire_terminal_deploy_run_worktrees(repo_root=repo, run_git=_run_git)

    assert [lane.state for lane in verdicts] == [LANE_BLOCKED]
    assert "operator-scratch.txt" in verdicts[0].reason
    assert (path / "operator-scratch.txt").read_text(encoding="utf-8") == "keep me"


def test_generated_caches_do_not_block_retirement(
    tmp_path: Path, statuses: dict[str, str]
) -> None:
    """A driver that executed here left __pycache__; that is not content."""
    repo = _repo(tmp_path / "repo")
    path = _driver_worktree(repo, "run-20260101-004")
    statuses["run-20260101-004"] = "succeeded"
    cache = path / "__pycache__"
    cache.mkdir()
    (cache / "driver.pyc").write_bytes(b"\x00")

    verdicts = retire_terminal_deploy_run_worktrees(repo_root=repo, run_git=_run_git)

    assert [lane.state for lane in verdicts] == [LANE_RETIRED]
    assert not path.exists()


def test_unreadable_run_status_keeps_the_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed: an unprovable verdict is never read as "finished"."""
    repo = _repo(tmp_path / "repo")
    path = _driver_worktree(repo, "run-20260101-005")
    monkeypatch.setattr(
        retirement,
        "_run_status",
        lambda _run_id: ("", "control plane unreachable"),
    )

    verdicts = retire_terminal_deploy_run_worktrees(repo_root=repo, run_git=_run_git)

    assert [lane.state for lane in verdicts] == [LANE_BLOCKED]
    assert "control plane unreachable" in verdicts[0].reason
    assert path.is_dir()


def test_an_unrecognised_status_keeps_the_worktree(
    tmp_path: Path, statuses: dict[str, str]
) -> None:
    """A status this build does not know is neither open nor finished."""
    repo = _repo(tmp_path / "repo")
    path = _driver_worktree(repo, "run-20260101-011")
    statuses["run-20260101-011"] = "quiesced"

    verdicts = retire_terminal_deploy_run_worktrees(repo_root=repo, run_git=_run_git)

    assert [lane.state for lane in verdicts] == [LANE_BLOCKED]
    assert "quiesced" in verdicts[0].reason
    assert path.is_dir()


def test_item_lanes_are_never_touched(tmp_path: Path, statuses: dict[str, str]) -> None:
    repo = _repo(tmp_path / "repo")
    lane = repo / ".worktrees" / "ITEM-1"
    lane.parent.mkdir(parents=True, exist_ok=True)
    _git(repo, "worktree", "add", "-b", "ITEM-1", str(lane), "HEAD")

    assert deploy_run_worktree_paths(_run_git, repo) == []
    assert retire_terminal_deploy_run_worktrees(repo_root=repo, run_git=_run_git) == ()
    assert lane.is_dir()


def test_the_caller_s_own_run_is_left_alone(
    tmp_path: Path, statuses: dict[str, str]
) -> None:
    """A driver sweeping before it pins its own source keeps its own slot."""
    repo = _repo(tmp_path / "repo")
    mine = _driver_worktree(repo, "run-20260101-006")
    statuses["run-20260101-006"] = "succeeded"

    verdicts = retire_terminal_deploy_run_worktrees(
        repo_root=repo, run_git=_run_git, keep_run_ids=("run-20260101-006",)
    )

    assert [lane.state for lane in verdicts] == [LANE_RUN_OPEN]
    assert mine.is_dir()


def test_assessment_changes_nothing(tmp_path: Path, statuses: dict[str, str]) -> None:
    repo = _repo(tmp_path / "repo")
    path = _driver_worktree(repo, "run-20260101-007")
    statuses["run-20260101-007"] = "succeeded"

    found = assess_deploy_run_worktrees(repo_root=repo, run_git=_run_git)

    assert [lane.state for lane in found] == [LANE_RETIRABLE]
    assert path.is_dir()


def test_one_finished_run_does_not_hold_up_another(
    tmp_path: Path, statuses: dict[str, str]
) -> None:
    """A blocked directory must not stop the reclaimable ones behind it."""
    repo = _repo(tmp_path / "repo")
    blocked = _driver_worktree(repo, "run-20260101-008")
    clean = _driver_worktree(repo, "run-20260101-009")
    statuses["run-20260101-008"] = "succeeded"
    statuses["run-20260101-009"] = "succeeded"
    (blocked / "scratch.txt").write_text("x", encoding="utf-8")

    verdicts = {
        lane.run_id: lane.state
        for lane in retire_terminal_deploy_run_worktrees(
            repo_root=repo, run_git=_run_git
        )
    }

    assert verdicts == {
        "run-20260101-008": LANE_BLOCKED,
        "run-20260101-009": LANE_RETIRED,
    }
    assert blocked.is_dir()
    assert not clean.exists()


def test_run_id_reads_back_from_the_directory_name() -> None:
    root = Path("/checkout")
    assert (
        run_id_for_driver_worktree(driver_worktree_path(root, "run-20260101-010"), root)
        == "run-20260101-010"
    )
    assert run_id_for_driver_worktree(root / ".worktrees" / "ITEM-7", root) == ""
    assert run_id_for_driver_worktree(Path("/elsewhere/deploy-run-1"), root) == ""
