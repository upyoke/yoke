"""No-change close-out uses the recorded landing behind a later unarmed PR."""

import subprocess

import pytest

from yoke_core.domain import item_merge_receipts as receipts
from yoke_core.domain import merge_queue_close_out as closing
from yoke_core.domain import merge_queue_landing_carrier as carriers
from yoke_core.domain import standalone_item_merge_converge as converging
from yoke_core.domain import standalone_item_merge_landed as landed
from yoke_core.domain.merge_queue_batch_receipt import BatchReceipt


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


@pytest.fixture
def prior_landing(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.test")
    (repo / "base.txt").write_text("base\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "item-lane")
    (repo / "feature.py").write_text("feature\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "feature")
    head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "Merge pull request #42", "item-lane")
    merge = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "item-lane")
    _git(repo, "merge", "-q", "--ff-only", "main")
    receipt = receipts.MergeReceipt(
        branch="item-lane",
        target="main",
        commit_sha=head,
        merge_sha=merge,
        touched_files=("feature.py",),
    )
    monkeypatch.setattr(receipts, "load", lambda *_a, **_k: receipt)
    monkeypatch.setattr(converging, "stale_unlanded_work", lambda **_k: "")
    monkeypatch.setattr(carriers, "_recorded_carrier", lambda *_a: ("", "offline"))
    monkeypatch.setattr(
        closing,
        "read_recorded_batch",
        lambda *_a, **_k: BatchReceipt(
            pr_num="42",
            merge_sha=merge,
            head_sha=merge,
            run_url="https://example.test/run",
        ),
    )
    monkeypatch.setattr(
        closing, "read_pr_changed_files", lambda *_a: (["feature.py"], "")
    )
    monkeypatch.setattr(closing, "stamp_merged_at", lambda *_a, **_k: None)
    monkeypatch.setattr(closing, "fast_forward_main_checkout", lambda *_a: "")
    monkeypatch.setattr(
        "yoke_core.domain.merge_queue_landed_candidate.landed_candidate_head",
        lambda *_a: pytest.fail("the later PR has no landing observation"),
    )
    return repo, receipt


def _close(repo):
    lane = landed.landed_lane(
        item_id=101,
        branch="item-lane",
        target="main",
        repo_root=str(repo),
        project="project",
    )
    assert lane is not None
    return converging.converge(
        item_id=101,
        public_ref="ITEM-1",
        project="project",
        repo_root=str(repo),
        lane=lane,
        queue_pr_number="43",
    )


def test_equal_lane_closes_against_its_prior_merge_without_an_observation(
    prior_landing, monkeypatch
):
    repo, receipt = prior_landing
    written = []
    monkeypatch.setattr(
        receipts, "record", lambda _item, value: written.append(value) or ""
    )

    outcome = _close(repo)

    assert outcome.ok, outcome.error
    assert outcome.pr_num == "42"
    assert outcome.commit_sha == receipt.commit_sha
    assert outcome.merge_sha == receipt.merge_sha
    assert written[0].commit_sha == receipt.commit_sha
    assert written[0].merge_sha == receipt.merge_sha
    assert _git(repo, "rev-parse", "item-lane") == _git(repo, "rev-parse", "main")


def test_equal_lane_without_a_completed_receipt_names_recovery(
    prior_landing, monkeypatch
):
    repo, _ = prior_landing
    monkeypatch.setattr(receipts, "load", lambda *_a, **_k: None)
    outcome = _close(repo)
    assert not outcome.ok
    assert "merge_recorded_landing_missing" in outcome.error
    assert "control-plane operator" in outcome.error


def test_recorded_merge_outside_target_refuses_before_writing(
    prior_landing, monkeypatch
):
    repo, receipt = prior_landing
    _git(repo, "checkout", "-qb", "unlanded")
    (repo / "other.py").write_text("unlanded\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "unlanded")
    other = _git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(
        receipts,
        "load",
        lambda *_a, **_k: receipts.MergeReceipt(
            branch=receipt.branch,
            target=receipt.target,
            commit_sha=receipt.commit_sha,
            merge_sha=other,
        ),
    )
    monkeypatch.setattr(
        receipts, "record", lambda *_a: pytest.fail("invalid landing must not write")
    )
    outcome = _close(repo)
    assert not outcome.ok
    assert "merge_candidate_not_landed" in outcome.error
