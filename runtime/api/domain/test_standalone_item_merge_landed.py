"""A lane the base branch already contains converges instead of re-landing.

Each case here is a close-out that ran a second time against work that had
already merged, and each one made things worse rather than merely wasting a
call: re-running the commit-bound QA recovery published a lane whose pull
request was sitting in the merge queue, and re-entering the queue read a train
run for a pull request GitHub had already merged.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain import merge_queue_close_out as queue_close_out
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain import standalone_item_merge_landed as landed
from yoke_core.domain import standalone_item_merge_receipt as receipts
from yoke_core.domain import standalone_item_merge_verify as verify
from yoke_core.domain.merge_queue_batch_receipt import BatchReceipt

LANE_SHA = "1" * 40
MERGE_SHA = "2" * 40
RECEIPT = receipts.MergeReceipt(
    branch="ITEM-1",
    target="main",
    commit_sha=LANE_SHA,
    merge_sha=MERGE_SHA,
    touched_files=("feature.py",),
)


def _probe(monkeypatch, *, branch_exists: bool, head: str, contains: tuple[str, ...]):
    monkeypatch.setattr(landed.git, "branch_exists", lambda *_a: branch_exists)
    monkeypatch.setattr(landed.git, "head_of", lambda *_a: head)
    monkeypatch.setattr(
        landed.git,
        "containing_ref",
        lambda _repo, commit, target: target if commit in contains else "",
    )
    monkeypatch.setattr(
        landed.git,
        "is_ancestor",
        lambda _repo, commit, _ref: commit in contains,
    )


def test_a_live_lane_the_base_contains_reports_the_landing(monkeypatch):
    _probe(monkeypatch, branch_exists=True, head=LANE_SHA, contains=(LANE_SHA,))
    monkeypatch.setattr(landed.receipts, "load", lambda *_a, **_k: RECEIPT)

    lane = landed.landed_lane(
        item_id=7, branch="ITEM-1", target="main",
        repo_root="/repo", project="yoke",
    )

    assert lane is not None
    assert lane.commit_sha == LANE_SHA
    assert lane.merge_sha == MERGE_SHA
    assert lane.touched_files == ("feature.py",)
    assert lane.source == "lane branch"


def test_a_lane_carrying_new_commits_has_not_landed(monkeypatch):
    """The branch is the authority while it exists, not an older receipt."""
    _probe(monkeypatch, branch_exists=True, head="9" * 40, contains=(LANE_SHA,))
    monkeypatch.setattr(
        landed.receipts,
        "load",
        lambda *_a, **_k: pytest.fail("an unlanded branch answers for itself"),
    )

    assert landed.landed_lane(
        item_id=7, branch="ITEM-1", target="main",
        repo_root="/repo", project="yoke",
    ) is None


def test_a_lane_fast_forwarded_onto_the_base_still_reports_the_receipt_head(
    monkeypatch,
):
    """A lane pointing at its own merge commit landed; it is not new work."""
    _probe(
        monkeypatch, branch_exists=True, head=MERGE_SHA,
        contains=(LANE_SHA, MERGE_SHA),
    )
    monkeypatch.setattr(landed.receipts, "load", lambda *_a, **_k: RECEIPT)

    lane = landed.landed_lane(
        item_id=7, branch="ITEM-1", target="main",
        repo_root="/repo", project="yoke",
    )

    assert lane is not None
    # The commit the merge was answerable for, not the merge commit the lane
    # happens to point at: evidence names what was verified.
    assert lane.commit_sha == LANE_SHA


def test_a_pruned_lane_falls_back_to_the_recorded_head(monkeypatch):
    _probe(monkeypatch, branch_exists=False, head="", contains=(LANE_SHA,))
    monkeypatch.setattr(landed.receipts, "load", lambda *_a, **_k: RECEIPT)

    lane = landed.landed_lane(
        item_id=7, branch="ITEM-1", target="main",
        repo_root="/repo", project="yoke", recorded_head=LANE_SHA,
    )

    assert lane is not None and lane.source == "recorded lane head"


def test_a_receipt_the_base_does_not_contain_is_not_a_landing(monkeypatch):
    _probe(monkeypatch, branch_exists=False, head="", contains=())
    monkeypatch.setattr(landed.receipts, "load", lambda *_a, **_k: RECEIPT)

    assert landed.landed_lane(
        item_id=7, branch="ITEM-1", target="main",
        repo_root="/repo", project="yoke",
    ) is None


def test_converging_records_the_merge_identity_a_retry_reads(monkeypatch):
    recorded: list[receipts.MergeReceipt] = []
    monkeypatch.setattr(
        landed, "fast_forward_main_checkout", lambda *_a: "",
    )
    monkeypatch.setattr(landed.git, "has_remote", lambda *_a: True)
    monkeypatch.setattr(landed.git, "fetch_target", lambda *_a: None)
    monkeypatch.setattr(landed.git, "is_ancestor", lambda *_a: True)
    monkeypatch.setattr(
        landed.git,
        "publish",
        lambda *_a: pytest.fail("a published landing needs no second push"),
    )
    monkeypatch.setattr(
        landed.receipts,
        "record",
        lambda _item, receipt, **_k: recorded.append(receipt) or "",
    )
    stamped: list[int] = []
    monkeypatch.setattr(
        "yoke_core.domain.standalone_item_merge.stamp_merged_at",
        lambda item_id: stamped.append(item_id) or None,
    )

    outcome = landed.converge(
        item_id=7,
        project="yoke",
        repo_root="/repo",
        lane=landed.LandedLane(
            branch="ITEM-1", target="main", commit_sha=LANE_SHA,
            merge_sha=MERGE_SHA, touched_files=("feature.py",),
            source="lane branch",
        ),
    )

    assert outcome.ok is True
    assert outcome.already_merged is True
    assert outcome.merge_sha == MERGE_SHA
    assert outcome.touched_files == ("feature.py",)
    assert stamped == [7]
    assert recorded and recorded[0].merge_sha == MERGE_SHA
    assert any("already landed" in warning for warning in outcome.warnings)


def test_converging_publishes_a_landing_that_never_reached_origin(monkeypatch):
    """A merge whose push died with the process still owes that push."""
    monkeypatch.setattr(landed, "fast_forward_main_checkout", lambda *_a: "")
    monkeypatch.setattr(landed.git, "has_remote", lambda *_a: True)
    monkeypatch.setattr(landed.git, "fetch_target", lambda *_a: None)
    monkeypatch.setattr(landed.git, "is_ancestor", lambda *_a: False)
    pushes: list[str] = []
    monkeypatch.setattr(
        landed.git,
        "publish",
        lambda _repo, target: (pushes.append(target), (True, ""))[1],
    )
    monkeypatch.setattr(landed.receipts, "record", lambda *_a, **_k: "")
    monkeypatch.setattr(
        "yoke_core.domain.standalone_item_merge.stamp_merged_at",
        lambda _item_id: None,
    )

    outcome = landed.converge(
        item_id=7,
        project="yoke",
        repo_root="/repo",
        lane=landed.LandedLane(
            branch="ITEM-1", target="main", commit_sha=LANE_SHA,
            merge_sha=MERGE_SHA, source="merge receipt",
        ),
    )

    assert pushes == ["main"]
    assert outcome.pushed is True


def test_a_landed_lane_never_reaches_the_verification_gate_or_the_queue(
    monkeypatch, capsys,
):
    """The two calls that made a re-entered close-out destructive."""
    item = {
        "id": 7,
        "public_ref": "ITEM-1",
        "status": "reviewing-implementation",
        "workflow": {"id": "dash"},
        "project": {"slug": "yoke"},
        "worktrees": [{"branch": "ITEM-1", "state": "active", "path": "/repo/lane"}],
    }
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *_a: (Path("/repo"), "main"),
    )
    monkeypatch.setattr(
        merge_cli.landed,
        "landed_lane",
        lambda **_kw: landed.LandedLane(
            branch="ITEM-1", target="main", commit_sha=LANE_SHA,
            merge_sha=MERGE_SHA, touched_files=("feature.py",),
            source="lane branch",
        ),
    )
    monkeypatch.setattr(
        verify,
        "qa_preflight",
        lambda *_a, **_k: pytest.fail("a landed lane must not re-run its case"),
    )
    monkeypatch.setattr(
        verify,
        "route_standalone_landing",
        lambda **_k: pytest.fail("a landed lane must not re-enter the queue"),
    )
    monkeypatch.setattr(landed, "fast_forward_main_checkout", lambda *_a: "")
    monkeypatch.setattr(landed.git, "has_remote", lambda *_a: False)
    monkeypatch.setattr(landed.receipts, "record", lambda *_a, **_k: "")
    monkeypatch.setattr(
        "yoke_core.domain.standalone_item_merge.stamp_merged_at",
        lambda _item_id: None,
    )

    assert merge_cli.run(["ITEM-1", "--skip-status", "--json"]) == 0
    envelope = capsys.readouterr().out
    assert '"already_merged": true' in envelope
    assert MERGE_SHA in envelope


def test_queue_handoff_reentry_runs_only_post_landing_bookkeeping(
    monkeypatch, capsys,
):
    item = {
        "id": 7,
        "public_ref": "ITEM-1",
        "status": "reviewing-implementation",
        "workflow": {"id": "dash"},
        "project": {"slug": "yoke"},
        "merge_queue": {"pr_number": "42", "enqueued_at": "2026-09-02T03:00Z"},
        "worktrees": [{"branch": "ITEM-1", "state": "active", "path": "/repo/lane"}],
    }
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *_a: (Path("/repo"), "main"),
    )
    monkeypatch.setattr(
        merge_cli.landed,
        "landed_lane",
        lambda **_kw: landed.LandedLane(
            branch="ITEM-1", target="main", commit_sha=LANE_SHA,
            merge_sha=MERGE_SHA, touched_files=("feature.py",),
            source="lane branch",
        ),
    )
    seen: dict = {}

    def record_landing(_ctx, **kwargs):
        seen.update(kwargs)
        return queue_close_out.QueueCloseOut(
            merge_sha=MERGE_SHA,
            touched_files=("feature.py",),
            batch=BatchReceipt(
                pr_num="42", head_sha=MERGE_SHA,
                run_url="https://github.test/runs/42",
            ),
        )

    monkeypatch.setattr(queue_close_out, "record_landing", record_landing)
    monkeypatch.setattr(
        verify,
        "qa_preflight",
        lambda *_a, **_k: pytest.fail("a landed queue member is not republished"),
    )

    assert merge_cli.run(["ITEM-1", "--skip-status", "--json"]) == 0
    envelope = capsys.readouterr().out
    assert seen["pr_num"] == "42"
    assert seen["member_snapshot"] == ("ITEM-1",)
    assert '"already_merged": true' in envelope


def test_containing_ref_names_the_remote_when_only_the_remote_has_it(
    monkeypatch,
):
    commands: list = []

    def fake_git(_repo_root, *args):
        commands.append(list(args))
        landed_here = args[:2] == ("merge-base", "--is-ancestor")
        remote_ref = landed_here and args[3] == "origin/main"
        return SimpleNamespace(
            returncode=0 if remote_ref else 1, stdout="origin\n", stderr="",
        )

    monkeypatch.setattr(git, "_git", fake_git)
    monkeypatch.setattr(git, "git_out", lambda _repo_root, *_a: "origin")

    assert git.containing_ref("/repo", LANE_SHA, "main") == "origin/main"
    assert ["fetch", "origin", "main"] in commands
