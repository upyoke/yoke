"""A standalone merge interrupted at any step converges on retry.

The engine's cleanup deletes the branch ref and removes the lane, so a run
that dies afterwards cannot re-derive its bookkeeping from git. These tests
walk a retry from each interruption point to the same completed state.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
import pytest

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.domain import standalone_item_merge as sim
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain import standalone_item_merge_receipt as receipts
from yoke_core.domain.json_helper import dumps_compact

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
    """Stands in for the events ledger, keeping the most complete receipt."""

    def __init__(self) -> None:
        self.saved: dict = {}

    def record(self, item_id, receipt, *, project="") -> str:
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

    def load(self, item_id, branch, target, *, project=""):
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
    return sim.merge_standalone_branch(
        item_id=ITEM_ID, branch=BRANCH, target=TARGET, repo_root=str(repo),
        project="yoke",
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


def _row(**context: object) -> dict:
    return {"envelope": dumps_compact({"context": context})}


class TestReceiptLedger:
    def test_recording_carries_the_merge_facts(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sent: dict = {}

        def capture(**kwargs):
            sent.update(kwargs)
            return FunctionCallResponse(
                success=True, function=kwargs["function_id"], version="v1",
                result={"emitted": True},
            )

        monkeypatch.setattr(receipts, "call_dispatcher", capture)
        note = receipts.record(
            ITEM_ID,
            receipts.MergeReceipt(
                branch=BRANCH, target=TARGET, commit_sha="abc",
                merge_sha="def", touched_files=("feature.txt",),
            ),
            project="yoke",
        )

        assert note == ""
        assert sent["function_id"] == "events.emit"
        payload = sent["payload"]
        assert payload["name"] == receipts.RECEIPT_EVENT_NAME
        assert payload["item_id"] == str(ITEM_ID)
        # events.emit is project-scoped over the dispatcher: an empty
        # project is refused and the receipt silently skipped.
        assert payload["project"] == "yoke"
        assert payload["context"]["touched_files"] == ["feature.txt"]

    def test_loading_folds_the_newest_non_empty_fields(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Newest first: the completed row's merge sha, the first row's files."""
        rows = [
            _row(branch=BRANCH, target=TARGET, commit_sha="abc",
                 merge_sha="def", touched_files=[]),
            _row(branch="other-lane", target=TARGET, commit_sha="zzz",
                 merge_sha="yyy", touched_files=["unrelated.txt"]),
            _row(branch=BRANCH, target=TARGET, commit_sha="abc",
                 merge_sha="", touched_files=["feature.txt"]),
        ]
        monkeypatch.setattr(
            receipts, "call_dispatcher",
            lambda **kwargs: FunctionCallResponse(
                success=True, function=kwargs["function_id"], version="v1",
                result={"rows": rows},
            ),
        )
        loaded = receipts.load(ITEM_ID, BRANCH, TARGET, project="yoke")

        assert loaded is not None
        assert loaded.commit_sha == "abc"
        assert loaded.merge_sha == "def"
        assert loaded.touched_files == ("feature.txt",)

    def test_the_emitter_is_visible_to_registry_discovery(self) -> None:
        """Discovery is how this event name reaches the registry and catalog."""
        from yoke_core.domain.events_registry_discovery import (
            _discover_python_event_names,
        )

        source = Path(receipts.__file__).read_text()

        assert receipts.RECEIPT_EVENT_NAME in _discover_python_event_names(source)

    def test_an_unreadable_ledger_reads_as_no_receipt(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def refuse(**_kwargs):
            raise RuntimeError("control plane unreachable")

        monkeypatch.setattr(receipts, "call_dispatcher", refuse)

        assert receipts.load(ITEM_ID, BRANCH, TARGET, project="yoke") is None
        assert "not recorded" in receipts.record(
            ITEM_ID,
            receipts.MergeReceipt(
                branch=BRANCH, target=TARGET, commit_sha="abc",
            ),
            project="yoke",
        )
