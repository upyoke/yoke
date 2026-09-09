"""A lane the base branch already contains converges instead of re-landing."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain import merge_queue_close_out as queue_close_out
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_converge as converging
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain import standalone_item_merge_landed as landed
from yoke_core.domain import item_merge_receipts as receipts
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
_LOOK = dict(item_id=7, branch="ITEM-1", target="main", repo_root="/repo")


def _probe(
    monkeypatch,
    *,
    branch_exists: bool,
    head: str,
    contains: tuple[str, ...],
    unlanded: tuple[str, ...] | None = ("9" * 40,),
):
    """Answer every read of the checkout, so no test reaches a real repo.

    ``unlanded`` is the patch-identity answer: a lane still carrying a commit
    of its own by default, which is what keeps these cases about shas.
    """
    monkeypatch.setattr(landed.git, "branch_exists", lambda *_a: branch_exists)
    monkeypatch.setattr(landed.git, "head_of", lambda *_a: head)
    monkeypatch.setattr(landed.git, "current_base_ref", lambda _repo, target: target)
    monkeypatch.setattr(landed.git, "unlanded_commits", lambda *_a: unlanded)
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


def _lane(**kw):
    return landed.landed_lane(**_LOOK, project="yoke", **kw)


def _item(**extra):
    row = {
        "id": 7,
        "public_ref": "ITEM-1",
        "status": "reviewing-implementation",
        "workflow": {"id": "dash"},
        "project": {"slug": "yoke"},
        "worktrees": [{"branch": "ITEM-1", "state": "active", "path": "/repo/lane"}],
    }
    row.update(extra)
    return row


def _wire_cli(monkeypatch, item, *, stale=""):
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(
        merge_cli,
        "_resolve_checkout",
        lambda *_a: (Path("/repo"), "main"),
    )
    monkeypatch.setattr(merge_cli.landed, "stale_unlanded_work", lambda **_k: stale)
    monkeypatch.setattr(
        merge_cli.landed,
        "landed_lane",
        lambda **_kw: landed.LandedLane(
            branch="ITEM-1",
            target="main",
            commit_sha=LANE_SHA,
            merge_sha=MERGE_SHA,
            touched_files=("feature.py",),
            source="lane branch",
        ),
    )


def test_a_live_lane_the_base_contains_reports_the_landing(monkeypatch):
    _probe(
        monkeypatch,
        branch_exists=True,
        head=LANE_SHA,
        contains=(LANE_SHA, MERGE_SHA),
    )
    monkeypatch.setattr(landed.receipts, "load", lambda *_a, **_k: RECEIPT)
    lane = _lane()
    assert lane is not None
    assert (lane.commit_sha, lane.merge_sha, lane.touched_files, lane.source) == (
        LANE_SHA,
        MERGE_SHA,
        ("feature.py",),
        "lane branch",
    )


def test_a_lane_carrying_new_commits_has_not_landed(monkeypatch):
    _probe(
        monkeypatch,
        branch_exists=True,
        head="9" * 40,
        contains=(LANE_SHA, MERGE_SHA),
    )
    monkeypatch.setattr(landed.receipts, "load", lambda *_a, **_k: RECEIPT)
    assert _lane() is None
    assert "fresh work item" in landed.stale_unlanded_work(**_LOOK)


def test_a_squashed_head_matching_the_receipt_has_landed(monkeypatch):
    _probe(monkeypatch, branch_exists=True, head=LANE_SHA, contains=(MERGE_SHA,))
    monkeypatch.setattr(landed.receipts, "load", lambda *_a, **_k: RECEIPT)
    lane = _lane()
    assert lane is not None and lane.commit_sha == LANE_SHA
    assert landed.stale_unlanded_work(**_LOOK) == ""


def test_a_lane_fast_forwarded_onto_the_base_still_reports_the_receipt_head(
    monkeypatch,
):
    _probe(
        monkeypatch,
        branch_exists=True,
        head=MERGE_SHA,
        contains=(LANE_SHA, MERGE_SHA),
    )
    monkeypatch.setattr(landed.receipts, "load", lambda *_a, **_k: RECEIPT)
    lane = _lane()
    assert lane is not None and lane.commit_sha == LANE_SHA


def test_a_pruned_lane_falls_back_to_the_recorded_head(monkeypatch):
    _probe(monkeypatch, branch_exists=False, head="", contains=(LANE_SHA,))
    monkeypatch.setattr(landed.receipts, "load", lambda *_a, **_k: RECEIPT)
    lane = _lane(recorded_head=LANE_SHA)
    assert lane is not None and lane.source == "recorded lane head"


def test_a_receipt_the_base_does_not_contain_is_not_a_landing(monkeypatch):
    _probe(monkeypatch, branch_exists=False, head="", contains=())
    monkeypatch.setattr(landed.receipts, "load", lambda *_a, **_k: RECEIPT)
    assert _lane() is None


def test_a_landed_lane_never_reaches_the_verification_gate_or_the_queue(
    monkeypatch,
    capsys,
):
    _wire_cli(monkeypatch, _item())
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
    monkeypatch.setattr(converging, "fast_forward_main_checkout", lambda *_a: "")
    monkeypatch.setattr(landed.git, "has_remote", lambda *_a: False)
    monkeypatch.setattr(landed.receipts, "record", lambda *_a, **_k: "")
    monkeypatch.setattr(
        "yoke_core.domain.standalone_item_merge.stamp_merged_at",
        lambda _i: None,
    )
    assert merge_cli.run(["ITEM-1", "--skip-status", "--json"]) == 0
    envelope = capsys.readouterr().out
    assert '"already_merged": true' in envelope and MERGE_SHA in envelope


def test_queue_handoff_reentry_runs_only_post_landing_bookkeeping(
    monkeypatch,
    capsys,
):
    _wire_cli(
        monkeypatch,
        _item(merge_queue={"pr_number": "42", "enqueued_at": "2026-09-02T03:00Z"}),
    )
    seen: dict = {}

    def record_landing(_ctx, **kwargs):
        seen.update(kwargs)
        return queue_close_out.QueueCloseOut(
            merge_sha=MERGE_SHA,
            touched_files=("feature.py",),
            batch=BatchReceipt(
                pr_num="42",
                head_sha=MERGE_SHA,
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
    assert seen["pr_num"] == "42" and seen["member_snapshot"] == ("ITEM-1",)
    assert '"already_merged": true' in capsys.readouterr().out


def test_merge_item_refuses_stale_landing_before_close_out(monkeypatch, capsys):
    _wire_cli(monkeypatch, _item(), stale="file a fresh work item")
    monkeypatch.setattr(
        merge_cli.converge,
        "converge",
        lambda **_k: pytest.fail("must not converge"),
    )
    monkeypatch.setattr(
        verify,
        "qa_preflight",
        lambda *_a, **_k: pytest.fail("must not verify"),
    )
    assert merge_cli.run(["ITEM-1", "--skip-status", "--json"]) == 1
    assert "fresh work item" in capsys.readouterr().out


def test_containing_ref_names_the_remote_when_only_the_remote_has_it(monkeypatch):
    commands: list = []

    def fake_git(_repo_root, *args):
        commands.append(list(args))
        remote = (
            args[:2] == ("merge-base", "--is-ancestor") and args[3] == "origin/main"
        )
        return SimpleNamespace(
            returncode=0 if remote else 1, stdout="origin\n", stderr=""
        )

    monkeypatch.setattr(git, "_git", fake_git)
    monkeypatch.setattr(git, "git_out", lambda _repo_root, *_a: "origin")
    assert git.containing_ref("/repo", LANE_SHA, "main") == "origin/main"
    assert ["fetch", "origin", "main"] in commands
