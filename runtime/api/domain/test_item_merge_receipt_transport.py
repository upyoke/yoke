"""The merge boundary records its receipt through the registered functions.

The merge runs on the machine holding the checkout, which over an https
control plane has no database to open, so the receipt crosses that boundary
as a function call. These tests pin the call shape and the degradation: an
unreachable store costs crash recovery, never the merge.
"""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.domain import item_merge_receipts as receipts

ITEM_ID = 7
BRANCH = "ITEM-1"
TARGET = "main"


def _ok(**kwargs) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True, function=kwargs["function_id"], version="v1", result={},
    )


def test_recording_carries_the_merge_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict = {}

    def capture(**kwargs):
        sent.update(kwargs)
        return _ok(**kwargs)

    monkeypatch.setattr(receipts, "call_dispatcher", capture)
    note = receipts.record(
        ITEM_ID,
        receipts.MergeReceipt(
            branch=BRANCH, target=TARGET, commit_sha="abc",
            merge_sha="def", touched_files=("feature.txt",),
        ),
    )

    assert note == ""
    assert sent["function_id"] == receipts.RECORD_FUNCTION_ID
    assert sent["target"].item_id == ITEM_ID
    payload = sent["payload"]
    assert payload["branch"] == BRANCH
    assert payload["target"] == TARGET
    assert payload["merge_sha"] == "def"
    assert payload["touched_files"] == ["feature.txt"]


def test_a_failure_and_a_settlement_use_the_same_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict] = []

    def capture(**kwargs):
        sent.append(kwargs["payload"])
        return _ok(**kwargs)

    monkeypatch.setattr(receipts, "call_dispatcher", capture)
    receipts.record_failure(
        ITEM_ID, branch=BRANCH, target=TARGET, label="merge failed",
        phase="branch-push", reason="remote rejected",
    )
    receipts.record_settlement(ITEM_ID, branch=BRANCH, target=TARGET)

    assert sent[0]["failure"] == {
        "label": "merge failed",
        "phase": "branch-push",
        "reason": "remote rejected",
    }
    assert sent[1]["settled"] is True
    assert {entry["branch"] for entry in sent} == {BRANCH}


def test_loading_returns_the_recorded_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        receipts, "call_dispatcher",
        lambda **kwargs: FunctionCallResponse(
            success=True, function=kwargs["function_id"], version="v1",
            result={
                "found": True,
                "entry": {
                    "commit_sha": "abc",
                    "merge_sha": "def",
                    "touched_files": ["feature.txt"],
                    "check_runs": [{"name": "ci", "conclusion": "success"}],
                },
            },
        ),
    )
    loaded = receipts.load(ITEM_ID, BRANCH, TARGET)

    assert loaded is not None
    assert loaded.commit_sha == "abc"
    assert loaded.merge_sha == "def"
    assert loaded.touched_files == ("feature.txt",)
    assert loaded.check_runs == (
        {"name": "ci", "status": "", "conclusion": "success", "url": ""},
    )


def test_a_missing_entry_reads_as_no_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        receipts, "call_dispatcher",
        lambda **kwargs: FunctionCallResponse(
            success=True, function=kwargs["function_id"], version="v1",
            result={"found": False, "entry": None},
        ),
    )

    assert receipts.load(ITEM_ID, BRANCH, TARGET) is None


def test_an_unreachable_store_degrades_instead_of_failing_the_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(**_kwargs):
        raise RuntimeError("control plane unreachable")

    monkeypatch.setattr(receipts, "call_dispatcher", refuse)

    assert receipts.load(ITEM_ID, BRANCH, TARGET) is None
    note = receipts.record(
        ITEM_ID,
        receipts.MergeReceipt(branch=BRANCH, target=TARGET, commit_sha="abc"),
    )
    assert "not recorded" in note
    assert "control plane unreachable" in note


def test_a_refused_write_names_the_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yoke_contracts.api.function_call import FunctionError

    monkeypatch.setattr(
        receipts, "call_dispatcher",
        lambda **kwargs: FunctionCallResponse(
            success=False, function=kwargs["function_id"], version="v1",
            error=FunctionError(code="target_invalid", message="no such item"),
        ),
    )
    note = receipts.record_settlement(ITEM_ID, branch=BRANCH, target=TARGET)

    assert "no such item" in note


class TestLandedIdentityIsNeverBorrowed:
    """A branch that contributed nothing must not be handed someone's merge.

    The changed-file fallback walks the merges between a branch's commit and
    the target. When the branch never advanced past the base it forked from,
    every merge on that walk belongs to somebody else, and returning the
    oldest one attributes an unrelated merge and its whole diff to this item.
    """

    @staticmethod
    def _repo(tmp_path):
        import subprocess

        root = tmp_path / "checkout"
        root.mkdir()

        def git(*args: str) -> str:
            return subprocess.run(
                ["git", "-C", str(root), *args],
                check=True, capture_output=True, text=True,
            ).stdout.strip()

        git("init", "-b", "main")
        git("config", "user.email", "test@test.com")
        git("config", "user.name", "Test")
        (root / "base.txt").write_text("base\n")
        git("add", "base.txt")
        git("commit", "-m", "base")
        base = git("rev-parse", "HEAD")

        git("checkout", "-b", "neighbour")
        (root / "neighbour.txt").write_text("neighbour\n")
        git("add", "neighbour.txt")
        git("commit", "-m", "neighbour work")
        git("checkout", "main")
        (root / "moved.txt").write_text("moved\n")
        git("add", "moved.txt")
        git("commit", "-m", "main moves on")
        git("merge", "--no-ff", "--no-edit", "neighbour")
        return root, base, git

    def test_a_branch_that_added_nothing_resolves_no_landing_merge(
        self, tmp_path,
    ) -> None:
        root, base, _git = self._repo(tmp_path)

        assert receipts.landing_merge_commit(str(root), "main", base) == ""
        assert receipts.touched_files_from_merge_commit(
            str(root), "main", base,
        ) == ()

    def test_a_branch_that_landed_resolves_its_own_merge(self, tmp_path) -> None:
        root, _base, git = self._repo(tmp_path)
        neighbour_head = git("rev-parse", "neighbour")

        landed = receipts.landing_merge_commit(str(root), "main", neighbour_head)

        assert landed
        assert receipts.touched_files_from_merge_commit(
            str(root), "main", neighbour_head,
        ) == ("neighbour.txt",)


class TestLandedMergeIdentity:
    """The recorded merge identity is the branch's own, or nothing."""

    def test_a_fresh_merge_takes_the_tip_it_just_created(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            receipts.git, "git_out", lambda *_a, **_k: "c" * 40,
        )

        assert receipts.landed_merge_identity(
            item_id=ITEM_ID, branch=BRANCH, target=TARGET,
            repo_root="/repo", already=False, commit_sha="a" * 40,
        ) == "c" * 40

    def test_an_already_contained_branch_never_reads_the_moved_tip(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The tip belongs to whoever moved the target since."""
        monkeypatch.setattr(
            receipts.git, "git_out",
            lambda *_a, **_k: pytest.fail("read the target tip"),
        )
        monkeypatch.setattr(
            receipts, "landing_merge_commit", lambda *_a, **_k: "d" * 40,
        )

        assert receipts.landed_merge_identity(
            item_id=ITEM_ID, branch=BRANCH, target=TARGET,
            repo_root="/repo", already=True, commit_sha="a" * 40,
        ) == "d" * 40

    def test_a_retry_falls_back_to_the_receipt_it_already_recorded(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(receipts, "landing_merge_commit", lambda *_a, **_k: "")
        monkeypatch.setattr(
            receipts, "load",
            lambda *_a, **_k: receipts.MergeReceipt(
                branch=BRANCH, target=TARGET, commit_sha="a" * 40,
                merge_sha="e" * 40,
            ),
        )

        assert receipts.landed_merge_identity(
            item_id=ITEM_ID, branch=BRANCH, target=TARGET,
            repo_root="/repo", already=True, commit_sha="a" * 40,
        ) == "e" * 40

    def test_a_branch_that_carried_nothing_in_has_no_merge_identity(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(receipts, "landing_merge_commit", lambda *_a, **_k: "")
        monkeypatch.setattr(receipts, "load", lambda *_a, **_k: None)

        assert receipts.landed_merge_identity(
            item_id=ITEM_ID, branch=BRANCH, target=TARGET,
            repo_root="/repo", already=True, commit_sha="a" * 40,
        ) == ""
