"""Close-out ordering behind pushed standalone commit conclusions."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from yoke_core.domain import standalone_item_merge as merge_boundary
from yoke_core.domain import standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_post_push as post_push
from yoke_core.domain import standalone_item_merge_receipt as receipts
from yoke_core.engines import merge_landed_lane_cleanup as lane_cleanup
from yoke_core.engines import merge_worktree_post_local as local_merge
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext


MERGE_SHA = "b" * 40
LANE_SHA = "a" * 40


def _wire_complete(monkeypatch, verdict):
    recorded = []
    monkeypatch.setattr(post_push.git, "git_out", lambda *_a: MERGE_SHA)
    monkeypatch.setattr(post_push.git, "publish", lambda *_a: (True, ""))
    monkeypatch.setattr(post_push.git, "has_remote", lambda *_a: True)
    monkeypatch.setattr(merge_boundary, "stamp_merged_at", lambda _item: None)
    monkeypatch.setattr(
        post_push.receipts,
        "record",
        lambda _item, receipt, **_kw: recorded.append(receipt) or "",
    )
    monkeypatch.setattr(post_push, "await_post_push_checks", lambda *_a: verdict)
    monkeypatch.setattr(
        post_push, "fast_forward_main_checkout", lambda *_a: "",
    )
    return recorded


def _complete():
    return post_push.complete(
        item_id=7,
        branch="ITEM-7",
        target="main",
        repo_root="/repo",
        project="yoke",
        commit_sha=LANE_SHA,
        touched=("changed.py",),
        already=False,
        resume_command="yoke merge item ITEM-7 --result fixed --verification green",
    )


def test_red_ci_records_the_run_and_preserves_the_lane(monkeypatch) -> None:
    run = post_push.CheckRun(
        name="release pin",
        status="completed",
        conclusion="failure",
        url="https://runs/failing",
    )
    recorded = _wire_complete(
        monkeypatch, post_push.PostPushVerdict("failed", runs=(run,)),
    )

    outcome = _complete()

    assert not outcome.ok
    assert outcome.merge_sha == MERGE_SHA
    assert "https://runs/failing" in outcome.error
    assert "yoke merge item ITEM-7" in outcome.error
    assert recorded[-1].check_runs == (run.evidence(),)


def test_green_ci_records_its_conclusion_without_retiring_the_lane(monkeypatch) -> None:
    run = post_push.CheckRun(
        name="suite",
        status="completed",
        conclusion="success",
        url="https://runs/green",
    )
    recorded = _wire_complete(
        monkeypatch, post_push.PostPushVerdict("passed", runs=(run,)),
    )

    outcome = _complete()

    assert outcome.ok
    assert recorded[-1].check_runs[0]["conclusion"] == "success"


def test_no_discovered_ci_leaves_lane_retirement_to_terminal_close_out(
    monkeypatch,
) -> None:
    recorded = _wire_complete(
        monkeypatch, post_push.PostPushVerdict("no_checks"),
    )

    outcome = _complete()

    assert outcome.ok
    assert len(recorded) == 1
    assert recorded[0].check_runs == ()


def test_cli_refusal_never_reaches_evidence_or_done_transition(
    monkeypatch, capsys,
) -> None:
    item = {
        "id": 7,
        "public_ref": "ITEM-7",
        "status": "reviewing-implementation",
        "workflow": {"id": "dash"},
        "project": {"slug": "yoke"},
        "worktrees": [{"branch": "ITEM-7", "path": "/repo/lane"}],
    }
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(
        merge_cli, "_resolve_checkout", lambda *_a: (Path("/repo"), "main"),
    )
    monkeypatch.setattr(merge_cli, "qa_preflight", lambda *_a, **_k: (LANE_SHA, ""))
    monkeypatch.setattr(
        merge_cli,
        "route_standalone_landing",
        lambda **_k: merge_boundary.StandaloneMergeOutcome(
            ok=False,
            exit_code=1,
            already_merged=False,
            commit_sha=LANE_SHA,
            merge_sha=MERGE_SHA,
            error="post-push CI failed (https://runs/failing); lane retained",
        ),
    )
    monkeypatch.setattr(
        merge_cli.evidence,
        "record",
        lambda **_k: (_ for _ in ()).throw(AssertionError("no evidence write")),
    )
    monkeypatch.setattr(
        merge_cli,
        "_transition_to_done",
        lambda *_a: (_ for _ in ()).throw(AssertionError("no done transition")),
    )

    result = merge_cli.run([
        "ITEM-7", "--result", "fixed", "--verification", "green", "--json",
    ])
    payload = json.loads(capsys.readouterr().out)

    assert result == 1
    assert "https://runs/failing" in payload["error"]


def test_local_engine_defers_standalone_lane_removal(monkeypatch) -> None:
    removed = []
    parent = SimpleNamespace(
        _print=lambda *_a, **_k: None,
        _run_git=lambda *_a, **_k: SimpleNamespace(
            returncode=0, stdout="", stderr="",
        ),
    )
    monkeypatch.setattr(local_merge, "_parent", lambda: parent)
    monkeypatch.setattr(local_merge, "_ensure_snapshot_for_project", lambda *_a: None)
    monkeypatch.setattr(local_merge, "_schema_refresh", lambda *_a: None)
    monkeypatch.setattr(local_merge, "_regenerate_views_advisory", lambda *_a: None)
    monkeypatch.setattr(local_merge, "_ensure_target_branch", lambda *_a: None)
    monkeypatch.setattr(
        local_merge, "_remove_lane", lambda *_a: removed.append("removed"),
    )
    ctx = MergeContext(
        args=MergeArgs(branch="ITEM-7", target="main", standalone=True),
        repo_root="/repo",
        worktree_path="/repo/.worktrees/ITEM-7",
        yoke_repo_root="/repo",
    )

    assert local_merge.do_local_merge(ctx) == 0
    assert removed == []


def test_lane_retirement_uses_the_local_target_without_a_remote(
    monkeypatch,
) -> None:
    commands = []

    def git(command, **_kwargs):
        commands.append(command)
        stdout = "" if command == ["remote"] else ""
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    released = []
    monkeypatch.setattr(lane_cleanup, "_lane_worktree", lambda *_a: None)
    monkeypatch.setattr(
        lane_cleanup,
        "release_lane_row",
        lambda item, branch, **_k: released.append((item, branch)),
    )
    monkeypatch.setattr(
        lane_cleanup,
        "delete_remote_branch_if_merged",
        lambda **_k: (_ for _ in ()).throw(AssertionError("no remote cleanup")),
    )

    warnings = lane_cleanup.prune_landed_lane(
        repo_root="/repo", branch="ITEM-7", target="main", item_id=7,
        run_git=git, emit=lambda *_a, **_k: None,
    )

    assert warnings == ()
    assert ["fetch", "origin", "main"] not in commands
    assert ["merge-base", "--is-ancestor", "ITEM-7", "main"] in commands
    assert released == [(7, "ITEM-7")]


def test_receipt_loader_preserves_observed_check_conclusions(monkeypatch) -> None:
    row = {"envelope": json.dumps({"context": {
        "branch": "ITEM-7",
        "target": "main",
        "commit_sha": LANE_SHA,
        "merge_sha": MERGE_SHA,
        "touched_files": ["changed.py"],
        "check_runs": [{
            "name": "suite", "status": "completed",
            "conclusion": "success", "url": "https://runs/green",
        }],
    }})}
    monkeypatch.setattr(
        receipts,
        "call_dispatcher",
        lambda **_k: SimpleNamespace(success=True, result={"rows": [row]}),
    )

    receipt = receipts.load(7, "ITEM-7", "main", project="yoke")

    assert receipt is not None
    assert receipt.check_runs[0]["conclusion"] == "success"
