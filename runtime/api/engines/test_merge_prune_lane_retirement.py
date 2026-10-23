"""A swept worker retires in durable state before merge source selection."""

from contextlib import nullcontext
import shutil
from types import SimpleNamespace

import pytest

from runtime.api.engines._merge_prune_test_helpers import _Conn, _git, _install, _repo
from runtime.api.fixtures.backlog import (
    insert_epic_task,
    insert_item,
    insert_item_worktree,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.api import service_client_structured_api_adapter as adapter
from yoke_core.domain import db_helpers, standalone_item_merge_cli as merge_cli
from yoke_core.domain import standalone_item_merge_landed as landed
from yoke_core.domain import standalone_item_merge as merge_domain
from yoke_core.domain import standalone_item_merge_verify as verify
from yoke_core.domain.handlers import item_worktrees, merge_engine_internal_ops as ops
from yoke_core.domain.item_worktrees import list_item_worktrees
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.engines import merge_worktree_safe_prune as prune


@pytest.mark.parametrize("absent", [False, True])
def test_pruned_worker_retires_row_and_surviving_worker_merges(
    test_db, monkeypatch, tmp_path, absent
):
    repo, worktree, branch = _repo(tmp_path)
    surviving = repo / ".worktrees" / "surviving"
    _git(repo, "worktree", "add", "-b", "surviving", str(surviving), "main")
    insert_item(test_db, id=917, workflow_id="epic", status="reviewing-implementation")
    retired = insert_item_worktree(
        test_db, item_id=917, branch=branch, path=str(worktree), lane_role="worker"
    )
    insert_epic_task(
        test_db,
        epic_id=917,
        task_num=1,
        status="release",
        item_worktree_id=retired["id"],
    )
    insert_item_worktree(
        test_db,
        item_id=917,
        branch="surviving",
        path=str(surviving),
        lane_role="worker",
    )
    public_ref = render_item_ref(test_db, 917, required=True)
    git_io, _lines = _install(monkeypatch, repo, _Conn(branch))
    monkeypatch.setattr(ops, "_connect_rw", lambda: nullcontext(test_db))
    monkeypatch.setattr(db_helpers, "connect", lambda: nullcontext(test_db))
    releases = []

    def dispatch(*, function_id, target, payload, **_kwargs):
        if function_id == "item_worktrees.release_merged_lane":
            assert target.public_ref == public_ref
            assert not worktree.exists()
            releases.append(payload["branch"])
            target = TargetRef(kind="item", item_id=917)
            handler = item_worktrees.handle_release_merged_lane
        else:
            assert function_id == "merge.prune.authority_verdict"
            handler = ops.handle_prune_authority_verdict
        outcome = handler(
            FunctionCallRequest(
                function=function_id,
                target=target,
                payload=payload,
                actor=ActorContext(session_id="prune-test"),
            )
        )
        assert outcome.primary_success, outcome.error
        return SimpleNamespace(success=True, result=outcome.result_payload)

    monkeypatch.setattr(prune, "call_dispatcher", dispatch)
    monkeypatch.setattr(adapter, "call_dispatcher", dispatch)
    if absent:
        shutil.rmtree(worktree)

    sweep = prune.prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    assert releases == [branch]
    assert sweep.removed == (str(worktree),)
    lanes = list_item_worktrees(test_db, 917)
    assert (
        next(lane for lane in lanes if lane["branch"] == branch)["state"] == "released"
    )
    assert [lane["branch"] for lane in lanes if lane["state"] == "active"] == [
        "surviving"
    ]
    item = {
        "id": 917,
        "public_ref": public_ref,
        "status": "reviewing-implementation",
        "project": {"slug": "yoke"},
        "workflow": {"id": "dash"},
        "worktrees": lanes,
        "qa_plan_attachments": [],
        "qa_requirements": [],
    }
    monkeypatch.setattr(merge_cli, "_resolve_item", lambda *_a: (item, ""))
    monkeypatch.setattr(merge_cli, "_session_holds_claim", lambda *_a: "")
    monkeypatch.setattr(landed, "landed_lane", lambda **_kw: None)
    monkeypatch.setattr(merge_cli, "_resolve_checkout", lambda *_a: (repo, "main"))
    calls = []

    def land(**kwargs):
        calls.append(kwargs)
        return merge_domain.StandaloneMergeOutcome(
            exit_code=0,
            ok=True,
            already_merged=False,
            commit_sha="a" * 40,
            merge_sha="b" * 40,
            touched_files=("README.md",),
            pushed=True,
            warnings=(),
        )

    monkeypatch.setattr(verify, "route_standalone_landing", land)
    monkeypatch.setattr(merge_domain, "sync_item_to_github", lambda *_a: None)
    monkeypatch.setattr(
        merge_cli.close_out, "transition_to_done", lambda **_kw: ("release", "")
    )
    assert merge_cli.run([public_ref, "--skip-status"]) == 0
    assert calls[0]["branch"] == "surviving"


def test_older_authority_response_preserves_lane(monkeypatch, tmp_path):
    repo, worktree, branch = _repo(tmp_path)
    git_io, _lines = _install(monkeypatch, repo, _Conn(branch))
    monkeypatch.setattr(prune, "_prune_verdict", lambda *_a: {"prunable": True})

    sweep = prune.prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    assert worktree.exists()
    assert sweep.removed == ()
    assert "prune_owner_identity_unavailable" in sweep.preserved[0].reason
    assert "update the serving control plane" in sweep.preserved[0].reason


@pytest.mark.parametrize("dirty", [False, True])
def test_failed_removal_or_dirty_lane_does_not_release_row(
    monkeypatch, tmp_path, dirty
):
    repo, worktree, branch = _repo(tmp_path)
    git_io, _lines = _install(monkeypatch, repo, _Conn(branch))
    if dirty:
        (worktree / "evidence").write_text("preserve")
    else:
        monkeypatch.setattr(
            prune,
            "remove_worktree",
            lambda *_a: SimpleNamespace(removed=False, reason="filesystem busy"),
        )
    monkeypatch.setattr(
        prune,
        "release_lane_row",
        lambda *_a, **_kw: pytest.fail("released preserved lane"),
    )

    sweep = prune.prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    assert worktree.exists()
    assert sweep.removed == ()
    assert len(sweep.preserved) == 1
