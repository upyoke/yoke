"""What close-out records for a lane whose work the base branch already has."""

from __future__ import annotations

import pytest

from yoke_core.domain import item_merge_receipts as receipts
from yoke_core.domain import standalone_item_merge_converge as converging
from yoke_core.domain import standalone_item_merge_landed as landed

LANE_SHA = "1" * 40
MERGE_SHA = "2" * 40


@pytest.fixture(autouse=True)
def disconnected(monkeypatch):
    monkeypatch.setattr(converging, "github_merge_enabled", lambda _p: False)


def test_converging_records_the_merge_identity_a_retry_reads(monkeypatch):
    recorded: list[receipts.MergeReceipt] = []
    monkeypatch.setattr(converging, "stale_unlanded_work", lambda **_k: "")
    monkeypatch.setattr(converging, "verified_target_sha", lambda *_a: MERGE_SHA)
    monkeypatch.setattr(converging, "verified_landing_identity", lambda *_a: MERGE_SHA)
    monkeypatch.setattr(converging, "fast_forward_main_checkout", lambda *_a: "")
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
        lambda item_id, **_kwargs: stamped.append(item_id) or None,
    )
    outcome = converging.converge(
        item_id=7,
        project="yoke",
        repo_root="/repo",
        lane=landed.LandedLane(
            branch="ITEM-1",
            target="main",
            commit_sha=LANE_SHA,
            merge_sha=MERGE_SHA,
            touched_files=("feature.py",),
            source="lane branch",
        ),
    )
    assert outcome.ok and outcome.already_merged and outcome.merge_sha == MERGE_SHA
    assert stamped == [7] and recorded[0].merge_sha == MERGE_SHA
    assert any("already landed" in warning for warning in outcome.warnings)


def test_converge_refuses_new_commits_without_recording(monkeypatch):
    stamped: list[int] = []
    monkeypatch.setattr(
        converging,
        "stale_unlanded_work",
        lambda **_k: "file a fresh work item",
    )
    monkeypatch.setattr(
        "yoke_core.domain.standalone_item_merge.stamp_merged_at",
        lambda item_id, **_kwargs: stamped.append(item_id),
    )
    outcome = converging.converge(
        item_id=7,
        project="yoke",
        repo_root="/repo",
        lane=landed.LandedLane(
            branch="ITEM-1",
            target="main",
            commit_sha=LANE_SHA,
            merge_sha=MERGE_SHA,
            source="lane branch",
        ),
    )
    assert not outcome.ok and "fresh work item" in outcome.error and stamped == []


def test_converging_publishes_a_landing_that_never_reached_origin(monkeypatch):
    monkeypatch.setattr(converging, "stale_unlanded_work", lambda **_k: "")
    monkeypatch.setattr(converging, "verified_target_sha", lambda *_a: MERGE_SHA)
    monkeypatch.setattr(converging, "verified_landing_identity", lambda *_a: MERGE_SHA)
    monkeypatch.setattr(converging, "fast_forward_main_checkout", lambda *_a: "")
    monkeypatch.setattr(landed.git, "has_remote", lambda *_a: True)
    monkeypatch.setattr(landed.git, "fetch_target", lambda *_a: None)
    monkeypatch.setattr(landed.git, "is_ancestor", lambda *_a: False)
    from yoke_core.domain.merge_landing_proof import LandingUnverified

    readings = iter((LandingUnverified("not landed"), MERGE_SHA))

    def proof(*_a):
        value = next(readings)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(converging, "verified_target_sha", proof)
    pushes: list[str] = []
    monkeypatch.setattr(
        landed.git,
        "publish",
        lambda _repo, target: (pushes.append(target), (True, ""))[1],
    )
    monkeypatch.setattr(landed.receipts, "record", lambda *_a, **_k: "")
    monkeypatch.setattr(
        "yoke_core.domain.standalone_item_merge.stamp_merged_at",
        lambda _i, **_kwargs: None,
    )
    outcome = converging.converge(
        item_id=7,
        project="yoke",
        repo_root="/repo",
        lane=landed.LandedLane(
            branch="ITEM-1",
            target="main",
            commit_sha=LANE_SHA,
            merge_sha=MERGE_SHA,
            source="merge receipt",
        ),
    )
    assert pushes == ["main"] and outcome.pushed is True


@pytest.mark.parametrize("kind", ["passed", "failed", "timed_out", "unreadable"])
def test_retry_rechecks_post_push_on_the_landing(monkeypatch, kind):
    from yoke_core.domain.project_github_auth_models import GITHUB_AUTHORITY_INSTALLATION

    seen = []
    monkeypatch.setattr(converging, "stale_unlanded_work", lambda **_k: "")
    monkeypatch.setattr(converging, "verified_target_sha", lambda *_a: MERGE_SHA)
    monkeypatch.setattr(converging, "verified_landing_identity", lambda *_a: MERGE_SHA)
    monkeypatch.setattr(converging.git, "has_remote", lambda *_a: True)
    monkeypatch.setattr(converging, "github_merge_enabled", lambda _p: True)
    monkeypatch.setattr(converging.receipts, "record", lambda *_a, **_k: "")
    monkeypatch.setattr(converging, "fast_forward_main_checkout", lambda *_a: "")
    monkeypatch.setattr(
        "yoke_core.domain.standalone_item_merge.stamp_merged_at", lambda *_a, **_k: ""
    )
    def checks(*args):
        seen.append(args)
        return converging.post_push.PostPushVerdict(kind)
    monkeypatch.setattr(converging.post_push, "await_post_push_checks", checks)
    outcome = converging.converge(
        item_id=7, project="example", repo_root="/repo", public_ref="ITEM-7",
        lane=landed.LandedLane(branch="lane", target="main", commit_sha=LANE_SHA),
    )
    assert seen == [("example", MERGE_SHA, GITHUB_AUTHORITY_INSTALLATION)]
    assert outcome.ok is (kind == "passed")
    assert outcome.already_merged
    if kind != "passed":
        assert "yoke merge item ITEM-7" in outcome.error
