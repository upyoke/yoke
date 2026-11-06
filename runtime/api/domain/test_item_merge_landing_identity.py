"""Fresh remote ancestry owns landing identity and failed publication refuses."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from runtime.api.domain.standalone_merge_simulation_support import git, make_checkout
from yoke_core.domain import standalone_item_merge_post_push as completion
from yoke_core.domain import merge_queue_close_out as queue
from yoke_core.domain.merge_landing_proof import LandingUnverified, verified_target_sha
from yoke_core.engines import merge_worktree_post_local as integration
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext


@pytest.fixture
def checkout(tmp_path, monkeypatch, request):
    repo = make_checkout(tmp_path)
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "--bare")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "origin", "main")
    candidate = git(repo, "rev-parse", "ITEM-1")
    mode = "--no-ff" if getattr(request, "param", False) else "--ff-only"
    git(repo, "merge", mode, "--no-edit", "ITEM-1")
    records, stamps, failures = [], [], []
    monkeypatch.setattr(completion, "github_merge_enabled", lambda *_a: False)
    monkeypatch.setattr(completion, "fast_forward_main_checkout", lambda *_a: "")
    monkeypatch.setattr(
        completion.receipts,
        "record",
        lambda _id, receipt: records.append(receipt) or "",
    )
    monkeypatch.setattr(
        completion.receipts,
        "record_failure",
        lambda _id, **kw: failures.append(kw) or "",
    )
    monkeypatch.setattr(
        "yoke_core.domain.standalone_item_merge.stamp_merged_at",
        lambda _id, **kw: stamps.append(kw) or None,
    )
    return repo, remote, candidate, records, stamps, failures


def complete(repo, candidate):
    return completion.complete(
        item_id=7,
        branch="ITEM-1",
        target="main",
        repo_root=str(repo),
        project="sample",
        authority="installation",
        commit_sha=candidate,
        touched=("feature.txt",),
        already=False,
    )


@pytest.mark.parametrize("push_ok", [False, True])
def test_push_that_did_not_land_never_records_a_landing(checkout, monkeypatch, push_ok):
    repo, _, candidate, records, stamps, failures = checkout
    monkeypatch.setattr(
        completion.git, "publish", lambda *_a: (push_ok, "push did not update remote")
    )
    result = complete(repo, candidate)
    assert not result.ok and not result.merge_sha
    if push_ok:
        assert "merge_candidate_not_landed" in result.error
        assert "governed merge command" in result.error
    else:
        assert "push did not update remote" in result.error
        assert "yoke merge item ITEM-1" in result.error
    assert not records and not stamps
    assert failures[0]["label"] == "merge_landing_unverified"
    assert git(repo, "rev-parse", "ITEM-1") == candidate


@pytest.mark.parametrize(
    "checkout", [False, True], indirect=True, ids=["fast-forward", "merge-commit"]
)
def test_normal_landing_records_the_fresh_remote_tip(checkout, monkeypatch):
    from yoke_core.domain import item_landings_close_out as landings

    repo, remote, candidate, records, stamps, _ = checkout
    target_sha = git(repo, "rev-parse", "main")
    sent = []
    monkeypatch.setattr(
        landings, "_record", lambda _item, payload: sent.append(payload) or ""
    )
    result = complete(repo, candidate)
    assert result.ok and result.pushed
    assert result.commit_sha == candidate
    assert result.merge_sha == target_sha == git(remote, "rev-parse", "main")
    assert records[0].merge_sha == result.merge_sha
    assert records[0].commit_sha == candidate
    assert stamps[0]["merge_sha"] == result.merge_sha
    lane, note = landings.close_out_lane(
        item_id=7, branch="ITEM-1", target="main", repo_root=str(repo), outcome=result
    )
    assert not note and lane.merge_sha == target_sha
    assert sent[0]["merge_sha"] == target_sha
    assert sent[0]["candidate_sha"] == candidate
    assert sent[0]["route"] == (
        "fast_forward" if target_sha == candidate else "standalone"
    )


def test_cached_tracking_ref_cannot_hide_a_failed_fetch(checkout):
    repo, _, candidate, _, _, _ = checkout
    git(repo, "push", "origin", "main")
    git(repo, "remote", "set-url", "origin", str(repo / "missing.git"))
    with pytest.raises(LandingUnverified, match="merge_landing_fetch_failed"):
        verified_target_sha(str(repo), "main", candidate)


def test_queue_close_out_refuses_before_any_landing_writes(checkout, monkeypatch):
    repo, _, candidate, records, stamps, failures = checkout
    monkeypatch.setattr(
        queue,
        "read_recorded_batch",
        lambda *_a, **_kw: pytest.fail("no batch read before ancestry proof"),
    )
    result = queue.record_landing(
        MergeContext(
            args=MergeArgs(branch="ITEM-1", target="main"), repo_root=str(repo)
        ),
        item_id=7,
        commit_sha=candidate,
        pr_num="42",
    )
    assert "merge_candidate_not_landed" in result.ci_evidence_refusal("42")
    assert not records and not stamps and failures


def test_local_checkout_refusal_does_not_merge_the_lane(monkeypatch):
    calls = []

    def run(args, **_kw):
        calls.append(args)
        return SimpleNamespace(
            returncode=1, stderr="main checked out elsewhere", stdout=""
        )

    parent = SimpleNamespace(_print=lambda *_a, **_kw: None, _run_git=run)
    monkeypatch.setattr(integration, "_parent", lambda: parent)
    ctx = MergeContext(
        args=MergeArgs(branch="ITEM-1", target="main", standalone=True),
        repo_root="/mapped/lane",
    )
    assert integration.do_local_merge(ctx) == 1
    assert calls == [["checkout", "main"]]


def test_checkout_mapping_to_a_relocated_lane_resolves_owning_main(
    tmp_path, monkeypatch
):
    from yoke_core.domain import standalone_item_merge_checkout as checkout_resolution
    from yoke_core.domain import worktree_preflight_repo_resolution as routing
    from yoke_core.engines import done_transition_gates as gates

    repo = make_checkout(tmp_path)
    lane = tmp_path / "relocated-lane"
    git(repo, "worktree", "add", str(lane), "ITEM-1")
    monkeypatch.setattr(
        routing,
        "resolve_preflight_lane_target",
        lambda **_kw: SimpleNamespace(
            error="", repo_root=str(lane), project_slug="sample"
        ),
    )
    monkeypatch.setattr(gates, "_resolve_default_branch", lambda *_a: "main")
    monkeypatch.setattr(gates, "_get_base_branch", lambda *_a: "main")
    resolved, target = checkout_resolution.resolve_checkout({}, "")
    assert resolved == repo and target == "main"


@pytest.mark.parametrize("no_changes", [False, True])
def test_pr_cleanup_preserves_lane_without_fresh_remote_proof(
    checkout, monkeypatch, no_changes
):
    from yoke_core.engines import merge_worktree as engine

    repo, _, candidate, _, _, _ = checkout
    lane = repo / "preserved-lane"
    lane.mkdir()
    monkeypatch.setattr(engine, "_print", lambda *_a, **_kw: None)
    monkeypatch.setattr(engine, "_emit_merge_event", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        engine,
        "_run_git",
        lambda *_a, **_kw: SimpleNamespace(returncode=0, stdout=candidate, stderr=""),
    )
    ctx = MergeContext(
        args=MergeArgs(branch="ITEM-1", target="main"),
        repo_root=str(repo),
        worktree_path=str(lane),
    )
    assert engine._post_merge_cleanup(ctx, no_changes=no_changes) == 1
    assert lane.is_dir()


def test_retry_cannot_converge_on_an_unpublished_local_landing(checkout, monkeypatch):
    from yoke_core.domain import standalone_item_merge_converge as convergence
    from yoke_core.domain.standalone_item_merge_landed import LandedLane

    repo, _, candidate, records, stamps, failures = checkout
    monkeypatch.setattr(convergence, "stale_unlanded_work", lambda **_kw: "")
    monkeypatch.setattr(convergence.git, "publish", lambda *_a: (False, "denied"))
    result = convergence.converge(
        item_id=7,
        project="sample",
        repo_root=str(repo),
        lane=LandedLane(branch="ITEM-1", target="main", commit_sha=candidate),
    )
    assert not result.ok and "denied" in result.error
    assert "yoke merge item ITEM-1" in result.error
    assert not records and not stamps and failures


def test_own_landing_is_recorded_when_main_advanced_after_the_landing(
    checkout, monkeypatch
):
    from yoke_core.domain.merge_queue_batch_receipt import BatchReceipt

    repo, remote, candidate, records, _, _ = checkout
    (repo / "neighbor.txt").write_text("neighbor\n")
    git(repo, "add", "neighbor.txt")
    git(repo, "commit", "-m", "advance default branch")
    git(repo, "push", "origin", "main")
    tip = git(remote, "rev-parse", "main")
    monkeypatch.setattr(
        queue,
        "read_recorded_batch",
        lambda *_a, **_kw: BatchReceipt(
            pr_num="42",
            merge_sha=candidate,
            head_sha=candidate,
            run_url="https://runs/42",
        ),
    )
    monkeypatch.setattr(
        queue, "read_pr_changed_files", lambda *_a: (("feature.txt",), "")
    )
    monkeypatch.setattr(queue, "repoint_to_landing_carrier", lambda *_a, **_kw: "")
    monkeypatch.setattr(queue, "stamp_merged_at", lambda *_a, **_kw: None)
    monkeypatch.setattr(queue, "fast_forward_main_checkout", lambda *_a: "")
    result = queue.record_landing(
        MergeContext(
            args=MergeArgs(branch="ITEM-1", target="main"), repo_root=str(repo)
        ),
        item_id=7,
        commit_sha=candidate,
        pr_num="42",
    )
    assert result.merge_sha == candidate and records[-1].merge_sha == candidate
    assert result.merge_sha != tip
    assert result.receipt_commit_sha == candidate


def test_local_publication_records_own_landing_after_later_push(checkout):
    repo, _, candidate, records, stamps, _ = checkout
    (repo / "neighbor.txt").write_text("neighbor\n")
    git(repo, "add", "neighbor.txt")
    git(repo, "commit", "-m", "later target push")
    later = git(repo, "rev-parse", "main")
    result = complete(repo, candidate)
    assert result.ok and result.merge_sha == candidate
    assert result.merge_sha != later
    assert records[-1].merge_sha == candidate
    assert stamps[-1]["merge_sha"] == candidate


@pytest.mark.parametrize("batch_names_train_tip", [False, True])
def test_delayed_pr_close_outs_do_not_share_the_last_items_merge(
    checkout, monkeypatch, batch_names_train_tip
):
    """Each member records its own merge, even when its batch names the tip."""
    from yoke_core.domain.merge_queue_batch_receipt import BatchReceipt

    repo, _, _, records, _, _ = checkout
    landings = {}
    for index in range(4):
        branch = f"feature-{index}"
        git(repo, "checkout", "-b", branch)
        (repo / f"{branch}.txt").write_text(f"{branch}\n")
        git(repo, "add", f"{branch}.txt")
        git(repo, "commit", "-m", branch)
        head = git(repo, "rev-parse", "HEAD")
        git(repo, "checkout", "main")
        git(repo, "merge", "--no-ff", "--no-edit", branch)
        landings[str(index)] = (head, git(repo, "rev-parse", "HEAD"))
    git(repo, "push", "origin", "main")
    final_merge = git(repo, "rev-parse", "main")
    monkeypatch.setattr(queue, "read_recorded_batch", lambda *_a, **_kw: None)

    def observe(_ctx, *, pr_num, **_kwargs):
        return BatchReceipt(
            pr_num=pr_num,
            merge_sha=final_merge if batch_names_train_tip else landings[pr_num][1],
            head_sha=final_merge,
            run_url="https://runs/shared-train",
        ), None

    monkeypatch.setattr(queue, "observe_batch", observe)
    monkeypatch.setattr(queue, "record_batch_evidence", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        queue, "read_pr_changed_files", lambda *_a: (("feature.txt",), "")
    )
    monkeypatch.setattr(queue, "repoint_to_landing_carrier", lambda *_a, **_kw: "")
    monkeypatch.setattr(queue, "stamp_merged_at", lambda *_a, **_kw: None)
    monkeypatch.setattr(queue, "fast_forward_main_checkout", lambda *_a: "")
    for pr_num, (head, merge) in list(landings.items())[:3]:
        result = queue.record_landing(
            MergeContext(
                args=MergeArgs(branch=f"feature-{pr_num}", target="main"),
                repo_root=str(repo),
            ),
            item_id=int(pr_num) + 1,
            commit_sha=head,
            pr_num=pr_num,
            resolve_landed_head=lambda _item, head=head: (head, ""),
        )
        assert not result.ci_evidence_refusal(pr_num)
        assert result.merge_sha == records[-1].merge_sha == merge
        assert result.receipt_commit_sha == head
        assert result.merge_sha != final_merge
    assert len({receipt.merge_sha for receipt in records}) == 3
