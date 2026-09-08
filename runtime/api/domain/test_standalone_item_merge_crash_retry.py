"""A standalone merge interrupted at any step converges on retry.

The engine's cleanup deletes the branch ref and removes the lane, so a run
that dies afterwards cannot re-derive its bookkeeping from git. These tests
walk a retry from each interruption point to the same completed state.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
import pytest

from yoke_core.domain import standalone_item_merge as sim
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain import standalone_item_merge_landed as landed
from yoke_core.domain import item_merge_receipts as receipts

ITEM_ID = 7
BRANCH = "ITEM-1"
TARGET = "main"


def _git_out(repo: Path, *args: str) -> str:
    run = subprocess.run(["git", "-C", str(repo), *args], check=True,
                         capture_output=True, text=True)
    return run.stdout.strip()


def _git(repo: Path, *args: str) -> None:
    _git_out(repo, *args)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A checkout whose base branch moved after the item branch forked.

    The divergence matters: it makes the landing a real merge commit rather
    than a fast-forward, which is the shape the merge-commit fallback reads.
    """
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "-b", TARGET)
    _git(root, "config", "user.email", "test@test.com")
    _git(root, "config", "user.name", "Test")
    (root / "base.txt").write_text("base\n")
    _git(root, "add", "base.txt")
    _git(root, "commit", "-m", "base")

    _git(root, "checkout", "-b", BRANCH)
    (root / "feature.txt").write_text("feature\n")
    _git(root, "add", "feature.txt")
    _git(root, "commit", "-m", "feature")

    _git(root, "checkout", TARGET)
    (root / "other.txt").write_text("other\n")
    _git(root, "add", "other.txt")
    _git(root, "commit", "-m", "base branch moves on")
    return root


class _ReceiptStore:
    """Stands in for the item's receipt document, folding each write in."""

    def __init__(self) -> None:
        self.saved: dict = {}

    def record(self, item_id, receipt) -> str:
        key = (item_id, receipt.branch, receipt.target)
        prior = self.saved.get(key) or receipt
        self.saved[key] = receipts.MergeReceipt(
            branch=receipt.branch,
            target=receipt.target,
            commit_sha=receipt.commit_sha or prior.commit_sha,
            merge_sha=receipt.merge_sha or prior.merge_sha,
            touched_files=receipt.touched_files or prior.touched_files,
        )
        return ""

    def load(self, item_id, branch, target):
        return self.saved.get((item_id, branch, target))


@pytest.fixture
def ledger(monkeypatch: pytest.MonkeyPatch) -> _ReceiptStore:
    store = _ReceiptStore()
    monkeypatch.setattr(receipts, "record", store.record)
    monkeypatch.setattr(receipts, "load", store.load)
    monkeypatch.setattr(sim, "stamp_merged_at", lambda item_id: None)
    return store


def _land(repo: Path) -> None:
    _git(repo, "checkout", TARGET)
    _git(repo, "merge", "--no-edit", BRANCH)


def _land_and_clean_up(repo: Path) -> None:
    """What the engine does: land the branch, then destroy its ref."""
    _land(repo)
    _git(repo, "branch", "-D", BRANCH)


def _merge(repo: Path) -> sim.StandaloneMergeOutcome:
    recorded = sim.git.git_out(str(repo), "rev-parse", BRANCH)
    return sim.merge_standalone_branch(
        item_id=ITEM_ID, branch=BRANCH, target=TARGET, repo_root=str(repo),
        project="yoke", commit_sha=recorded,
    )


def _engine_that(action):
    return lambda **_kwargs: action()


class TestInterruptedMergeConverges:
    def test_a_cleanup_crash_after_the_merge_still_completes(
        self, repo: Path, ledger: _ReceiptStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The reported live failure: merged, then raised removing the lane."""
        def crash_after_landing():
            _land_and_clean_up(repo)
            raise ModuleNotFoundError("No module named 'yoke_core.domain.x'")

        monkeypatch.setattr(
            sim, "_run_merge_engine", _engine_that(crash_after_landing),
        )
        outcome = _merge(repo)

        assert outcome.ok
        assert outcome.touched_files == ("feature.txt",)
        assert outcome.merge_sha == _git_out(repo, "rev-parse", TARGET)
        assert any("cleanup" in warning for warning in outcome.warnings)

    def test_a_raise_before_the_branch_lands_is_still_a_failure(
        self, repo: Path, ledger: _ReceiptStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def crash_before_landing():
            raise RuntimeError("preflight refused")

        monkeypatch.setattr(
            sim, "_run_merge_engine", _engine_that(crash_before_landing),
        )
        outcome = _merge(repo)

        assert not outcome.ok
        assert "before the branch landed" in outcome.error

    @pytest.mark.parametrize("false_merge_sha", ["", "commit"])
    def test_an_unlanded_receipt_resumes_the_real_merge_path(
        self,
        repo: Path,
        ledger: _ReceiptStore,
        monkeypatch: pytest.MonkeyPatch,
        false_merge_sha: str,
    ) -> None:
        commit_sha = _git_out(repo, "rev-parse", BRANCH)
        ledger.record(
            ITEM_ID,
            receipts.MergeReceipt(
                branch=BRANCH,
                target=TARGET,
                commit_sha=commit_sha,
                merge_sha=commit_sha if false_merge_sha else "",
                touched_files=("feature.txt",),
            ),
        )
        assert (
            landed.landed_lane(
                item_id=ITEM_ID,
                branch=BRANCH,
                target=TARGET,
                repo_root=str(repo),
                project="yoke",
            )
            is None
        )

        def land_now():
            _land(repo)
            return 0, ""

        monkeypatch.setattr(sim, "_run_merge_engine", _engine_that(land_now))
        outcome = _merge(repo)
        assert outcome.ok and git.is_ancestor(str(repo), commit_sha, TARGET)

    def test_a_retry_with_the_ref_gone_converges_from_the_receipt(
        self, repo: Path, ledger: _ReceiptStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Death between the merge and the caller's close-out."""
        def land_then_die():
            _land_and_clean_up(repo)
            raise KeyboardInterrupt

        monkeypatch.setattr(sim, "_run_merge_engine", _engine_that(land_then_die))
        with pytest.raises(KeyboardInterrupt):
            _merge(repo)

        monkeypatch.setattr(
            sim, "_run_merge_engine",
            lambda **_k: pytest.fail("the engine must not run again"),
        )
        retried = _merge(repo)

        assert retried.ok
        assert retried.already_merged
        assert retried.touched_files == ("feature.txt",)
        assert retried.merge_sha == _git_out(repo, "rev-parse", TARGET)

    def test_repeated_retries_report_one_identity(
        self, repo: Path, ledger: _ReceiptStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def land_and_clean_up():
            _land_and_clean_up(repo)
            return 0, ""

        monkeypatch.setattr(
            sim, "_run_merge_engine", _engine_that(land_and_clean_up),
        )
        identities = {
            (o.commit_sha, o.merge_sha, o.touched_files)
            for o in (_merge(repo), _merge(repo), _merge(repo))
        }

        assert len(identities) == 1
        assert identities.pop()[2] == ("feature.txt",)

    def test_an_already_merged_ref_reports_the_recorded_touched_files(
        self, repo: Path, ledger: _ReceiptStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The branch survives cleanup, so git reports an empty diff."""
        def land_keeping_the_ref():
            _land(repo)
            return 0, ""

        monkeypatch.setattr(
            sim, "_run_merge_engine", _engine_that(land_keeping_the_ref),
        )
        _merge(repo)
        assert git.changed_files(str(repo), BRANCH, TARGET) == ()

        monkeypatch.setattr(
            sim, "_run_merge_engine",
            lambda **_k: pytest.fail("the engine must not run again"),
        )
        retried = _merge(repo)

        assert retried.already_merged
        assert retried.touched_files == ("feature.txt",)

    def test_without_a_receipt_the_merge_commit_answers(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A merge that landed before any receipt existed still resolves."""
        monkeypatch.setattr(sim, "stamp_merged_at", lambda item_id: None)
        monkeypatch.setattr(receipts, "record", lambda *_a, **_k: "")
        monkeypatch.setattr(receipts, "load", lambda *_a, **_k: None)
        _land(repo)

        outcome = _merge(repo)

        assert outcome.already_merged
        assert outcome.touched_files == ("feature.txt",)


class TestUnrecoverableStates:
    def test_a_missing_branch_with_no_receipt_refuses(
        self, repo: Path, ledger: _ReceiptStore,
    ) -> None:
        _git(repo, "branch", "-D", BRANCH)
        outcome = _merge(repo)

        assert not outcome.ok
        assert "does not exist" in outcome.error

    def test_a_receipt_commit_absent_from_the_target_refuses(
        self, repo: Path, ledger: _ReceiptStore,
    ) -> None:
        commit_sha = _git_out(repo, "rev-parse", BRANCH)
        ledger.record(
            ITEM_ID,
            receipts.MergeReceipt(
                branch=BRANCH, target=TARGET, commit_sha=commit_sha,
                touched_files=("feature.txt",),
            ),
        )
        _git(repo, "branch", "-D", BRANCH)
        outcome = _merge(repo)

        assert not outcome.ok
        assert "is not contained by" in outcome.error
