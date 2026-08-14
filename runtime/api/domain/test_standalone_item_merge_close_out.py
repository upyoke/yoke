"""A landed merge must be able to finish closing the item out.

Both close-out failures this covers left an item merged but not done: the
terminal transition refused because the local checkout had not seen the
landing, and the merge identity it was handed named a commit the landing
rewrote. Either way the merge itself had already happened, so refusing the
close-out strands the item rather than protecting anything.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from yoke_core.domain import standalone_item_merge as sim
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_evidence as merge_evidence
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain import standalone_item_merge_recovery as recovery
from yoke_core.domain import standalone_item_merge_receipt as receipts
from yoke_core.domain.standalone_item_merge import StandaloneMergeOutcome

LANE_SHA = "1" * 40
MERGE_SHA = "2" * 40


def _transition_calls(monkeypatch) -> list:
    """Capture every close-out call, whichever module makes it."""
    calls: list = []

    def dispatch(*, function_id, target, payload=None, **_kw):
        calls.append((function_id, payload))
        return SimpleNamespace(success=True, result={}, error=None)

    monkeypatch.setattr(merge_cli, "call_dispatcher", dispatch)
    monkeypatch.setattr(merge_evidence, "call_dispatcher", dispatch)
    return calls


def test_transition_accepts_a_landing_only_the_remote_has_seen(monkeypatch):
    """A queue merge lands on GitHub; the local base branch lags behind."""
    fetched: list = []

    def is_landed(repo_root, commit, target):
        fetched.append((commit, target))
        return commit == LANE_SHA

    monkeypatch.setattr(git, "is_landed", is_landed)
    calls = _transition_calls(monkeypatch)

    error = merge_cli._transition_to_done(
        7,
        "reviewing-implementation",
        Path("/repo"),
        "main",
        LANE_SHA,
        MERGE_SHA,
    )

    assert error == ""
    assert fetched[0] == (LANE_SHA, "main")
    assert calls[0][0] == "lifecycle.transition.execute"


def test_transition_accepts_the_merge_commit_when_the_lane_head_was_rewritten(
    monkeypatch,
):
    """A squash or queue merge can leave only the merge commit reachable."""
    monkeypatch.setattr(
        git,
        "is_landed",
        lambda repo_root, commit, target: commit == MERGE_SHA,
    )
    calls = _transition_calls(monkeypatch)

    error = merge_cli._transition_to_done(
        7,
        "reviewing-implementation",
        Path("/repo"),
        "main",
        LANE_SHA,
        MERGE_SHA,
    )

    assert error == ""
    assert calls[0][1]["target_status"] == "done"


def test_transition_still_refuses_a_commit_no_branch_carries(monkeypatch):
    monkeypatch.setattr(git, "is_landed", lambda *_args: False)

    def forbidden(**_kw):
        raise AssertionError("an unlanded commit must not transition")

    monkeypatch.setattr(merge_cli, "call_dispatcher", forbidden)

    error = merge_cli._transition_to_done(
        7,
        "reviewing-implementation",
        Path("/repo"),
        "main",
        LANE_SHA,
        MERGE_SHA,
    )

    assert "is not reachable from 'main'" in error


def test_a_queue_landed_item_closes_out_with_its_own_file_set(monkeypatch):
    """A landed merge must not strand at the evidence write.

    The queue route returned no touched files, so the evidence writer
    refused every queue-landed item after its branch had already merged.
    The file set travels back with the landing outcome for exactly this
    call, whichever boundary produced it.
    """
    item = {
        "id": 7,
        "public_ref": "ITEM-1",
        "status": "reviewing-implementation",
        "workflow": {"id": "dash"},
        "project": {"slug": "yoke"},
        "worktrees": [{"path": "/repo/.worktrees/ITEM-1", "branch": "ITEM-1"}],
    }
    monkeypatch.setattr(
        merge_cli,
        "_resolve_item",
        lambda ref, project: (item, ""),
    )
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(
        merge_cli,
        "_resolve_checkout",
        lambda item, target: (Path("/repo"), "main"),
    )
    monkeypatch.setattr(
        merge_cli,
        "qa_preflight",
        lambda item, *, item_ref, repo_root, branch: (LANE_SHA, ""),
    )
    monkeypatch.setattr(
        merge_cli,
        "route_standalone_landing",
        lambda **_kw: StandaloneMergeOutcome(
            ok=True,
            exit_code=0,
            already_merged=False,
            commit_sha=LANE_SHA,
            merge_sha=MERGE_SHA,
            touched_files=("a.py", "docs/b.md"),
            pushed=True,
        ),
    )
    monkeypatch.setattr(sim, "sync_item_to_github", lambda item_id: None)
    monkeypatch.setattr(git, "is_landed", lambda *_args: True)
    calls = _transition_calls(monkeypatch)

    exit_code = merge_cli.run(
        ["ITEM-1", "--result", "landed", "--verification", "merge_group green"],
    )

    assert exit_code == 0
    payloads = dict(calls)
    evidence = payloads["direct_workflow.dash.evidence"]
    assert evidence["touched_files"] == ["a.py", "docs/b.md"]
    assert evidence["commit_sha"] == LANE_SHA
    assert evidence["merge_sha"] == MERGE_SHA
    assert payloads["lifecycle.transition.execute"]["target_status"] == "done"
    call_names = [name for name, _payload in calls]
    assert call_names.index("direct_workflow.dash.evidence") < call_names.index(
        "lifecycle.transition.execute"
    )


def test_landed_receipt_reacquires_close_out_authority(monkeypatch):
    """A retry proves containment before taking a replacement claim."""
    receipt = receipts.MergeReceipt(
        branch="ITEM-1",
        target="main",
        commit_sha=LANE_SHA,
        merge_sha=MERGE_SHA,
        touched_files=("a.py",),
    )
    monkeypatch.setattr(recovery.receipts, "load", lambda *_a, **_k: receipt)
    monkeypatch.setattr(
        recovery.git,
        "is_landed",
        lambda _repo, sha, _target: sha == MERGE_SHA,
    )
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(success=True, result={"claim_id": 9}, error=None)

    monkeypatch.setattr(recovery, "call_dispatcher", dispatch)

    recovered, error = recovery.reacquire_landed_claim(
        item_id=7,
        branch="ITEM-1",
        target="main",
        repo_root="/repo",
        project="yoke",
        session_id="session-1",
    )

    assert error == ""
    assert recovered == receipt
    assert calls[0]["function_id"] == "claims.work.acquire"
    assert calls[0]["actor"].session_id == "session-1"


def test_uncontained_receipt_cannot_reacquire_close_out_authority(monkeypatch):
    receipt = receipts.MergeReceipt(
        branch="ITEM-1",
        target="main",
        commit_sha=LANE_SHA,
    )
    monkeypatch.setattr(recovery.receipts, "load", lambda *_a, **_k: receipt)
    monkeypatch.setattr(recovery.git, "is_landed", lambda *_a: False)
    monkeypatch.setattr(
        recovery,
        "call_dispatcher",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("an unlanded receipt cannot acquire a claim")
        ),
    )

    recovered, error = recovery.reacquire_landed_claim(
        item_id=7,
        branch="ITEM-1",
        target="main",
        repo_root="/repo",
        project="yoke",
        session_id="session-1",
    )

    assert recovered is None
    assert "not contained" in error


def test_merge_retry_uses_recovered_head_then_finishes_close_out(monkeypatch):
    item = {
        "id": 7,
        "public_ref": "ITEM-1",
        "status": "reviewing-implementation",
        "workflow": {"id": "dash"},
        "project": {"slug": "yoke"},
        "worktrees": [],
    }
    receipt = receipts.MergeReceipt(
        branch="ITEM-1",
        target="main",
        commit_sha=LANE_SHA,
        merge_sha=MERGE_SHA,
        touched_files=("a.py",),
    )
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(
        merge_cli,
        "_session_holds_claim",
        lambda *_a: "no live work claim on this item",
    )
    monkeypatch.setattr(
        merge_cli,
        "_resolve_checkout",
        lambda *_a: (Path("/repo"), "main"),
    )
    monkeypatch.setattr(
        recovery,
        "reacquire_landed_claim",
        lambda **_k: (receipt, ""),
    )
    preflight_heads = []

    def preflight(recovered_item, **_kwargs):
        preflight_heads.append(recovered_item["worktrees"][-1]["commit_sha"])
        return LANE_SHA, ""

    monkeypatch.setattr(merge_cli, "qa_preflight", preflight)
    monkeypatch.setattr(
        merge_cli,
        "route_standalone_landing",
        lambda **_k: StandaloneMergeOutcome(
            ok=True,
            exit_code=0,
            already_merged=True,
            commit_sha=LANE_SHA,
            merge_sha=MERGE_SHA,
            touched_files=("a.py",),
            pushed=True,
        ),
    )
    monkeypatch.setattr(sim, "sync_item_to_github", lambda _item_id: None)
    monkeypatch.setattr(git, "is_landed", lambda *_a: True)
    calls = _transition_calls(monkeypatch)

    exit_code = merge_cli.run(
        ["ITEM-1", "--result", "landed", "--verification", "green"],
    )

    assert exit_code == 0
    assert preflight_heads == [LANE_SHA]
    assert [name for name, _payload in calls][-2:] == [
        "direct_workflow.dash.evidence",
        "lifecycle.transition.execute",
    ]


def test_is_landed_consults_the_remote_before_refusing(monkeypatch):
    commands: list = []

    def fake_git(repo_root, *args):
        commands.append(list(args))
        landed = args[:2] == ("merge-base", "--is-ancestor")
        remote_ref = landed and args[3] == "origin/main"
        return SimpleNamespace(
            returncode=0 if remote_ref else 1,
            stdout="origin\n",
            stderr="",
        )

    monkeypatch.setattr(git, "_git", fake_git)
    monkeypatch.setattr(git, "git_out", lambda repo_root, *args: "origin")

    assert git.is_landed("/repo", LANE_SHA, "main") is True
    assert ["fetch", "origin", "main"] in commands


def test_is_landed_is_false_without_a_commit(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("no git read is needed without a commit")

    monkeypatch.setattr(git, "_git", forbidden)

    assert git.is_landed("/repo", "", "main") is False
