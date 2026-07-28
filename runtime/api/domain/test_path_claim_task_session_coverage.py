"""Physical worker/integration lane authorization for task-bound claims."""

from __future__ import annotations

from runtime.api.domain.path_claim_task_test_support import (
    bind_claim,
    seed_epic,
    seed_integration_lane,
    seed_item_claim,
    seed_session,
    seed_target,
    seed_worker_task,
)
from yoke_core.domain.check_path_claim_coverage_at_commit import _decide
from yoke_core.domain.lint_worktree_path_invariants import (
    WorktreeInvariantContext,
)
from yoke_core.domain.path_claim_active_claim_lookup import (
    resolve_active_claim_for_session,
)
from yoke_core.domain.path_claim_target_resolver import (
    ClaimContext,
    OUT_OF_CLAIM,
    evaluate_target,
)
from yoke_core.domain.path_claim_task_session_coverage import (
    effective_targets_for_session,
)


def _seed_lanes_and_claims(test_db, tmp_path):
    item_id = seed_epic(test_db, item_id=21201)
    cases = (
        (1, "planned", "src/one.py"),
        (2, "planned", "src/two.py"),
        (3, "done", "src/done.py"),
        (4, "stopped", "src/stopped.py"),
        (5, "failed", "src/failed.py"),
    )
    lanes = {}
    for task_num, task_status, path in cases:
        lanes[task_num] = seed_worker_task(
            test_db,
            item_id=item_id,
            task_num=task_num,
            lane_path=tmp_path / f"worker-{task_num}",
            task_status=task_status,
            budget_path=path,
        )
        target_id = seed_target(test_db, item_id=item_id, path=path)
        claim_id = seed_item_claim(
            test_db,
            item_id=item_id,
            target_ids=(target_id,),
        )
        bind_claim(
            test_db,
            claim_id=claim_id,
            item_id=item_id,
            task_num=task_num,
        )
    integration_path = tmp_path / "integration"
    seed_integration_lane(
        test_db,
        item_id=item_id,
        lane_path=integration_path,
    )
    return item_id, lanes, integration_path


def test_worker_lane_uses_only_live_task_claim_even_with_parent_claim(
    test_db,
    tmp_path,
) -> None:
    item_id, _lanes, _integration = _seed_lanes_and_claims(
        test_db,
        tmp_path,
    )
    session_id = "worker-one"
    seed_session(
        test_db,
        session_id=session_id,
        item_id=item_id,
        task_num=1,
    )
    worker_path = tmp_path / "worker-1"

    targets = effective_targets_for_session(
        test_db,
        session_id=session_id,
        item_id=item_id,
        target_path="src/one.py",
        cwd=str(worker_path),
    )

    assert targets == (("src/one.py", "file"),)


def test_worker_lane_without_matching_task_claim_has_no_effective_scope(
    test_db,
    tmp_path,
) -> None:
    item_id, _lanes, _integration = _seed_lanes_and_claims(
        test_db,
        tmp_path,
    )
    session_id = "parent-only"
    seed_session(test_db, session_id=session_id, item_id=item_id)

    assert (
        effective_targets_for_session(
            test_db,
            session_id=session_id,
            item_id=item_id,
            target_path="src/one.py",
            cwd=str(tmp_path / "worker-1"),
        )
        == ()
    )


def test_integration_lane_unions_eligible_tasks_including_done(
    test_db,
    tmp_path,
) -> None:
    item_id, _lanes, integration_path = _seed_lanes_and_claims(
        test_db,
        tmp_path,
    )
    session_id = "integrator"
    seed_session(test_db, session_id=session_id, item_id=item_id)

    targets = effective_targets_for_session(
        test_db,
        session_id=session_id,
        item_id=item_id,
        target_path="src/one.py",
        cwd=str(integration_path),
    )

    assert targets == (
        ("src/done.py", "file"),
        ("src/one.py", "file"),
        ("src/two.py", "file"),
    )


def test_live_edit_resolution_denies_sibling_task_in_worker_lane(
    test_db,
    tmp_path,
) -> None:
    item_id, _lanes, _integration = _seed_lanes_and_claims(
        test_db,
        tmp_path,
    )
    session_id = "edit-worker"
    seed_session(
        test_db,
        session_id=session_id,
        item_id=item_id,
        task_num=1,
    )
    worker_path = tmp_path / "worker-1"
    claim = resolve_active_claim_for_session(
        session_id=session_id,
        conn=test_db,
        target_path="src/two.py",
        cwd=str(worker_path),
    )

    assert claim is not None
    assert claim["covered_paths"] == ["src/one.py"]
    failure = evaluate_target(
        target_path="src/two.py",
        cwd=str(worker_path),
        ctx=ClaimContext.from_claim(claim),
        conn=test_db,
    )
    assert failure is not None
    assert failure.mode == OUT_OF_CLAIM


def test_precommit_uses_worker_scope_and_integration_union(
    test_db,
    tmp_path,
    monkeypatch,
) -> None:
    from yoke_core.domain import check_path_claim_coverage_at_commit as gate

    item_id, _lanes, integration_path = _seed_lanes_and_claims(
        test_db,
        tmp_path,
    )
    worker_session = "commit-worker"
    seed_session(
        test_db,
        session_id=worker_session,
        item_id=item_id,
        task_num=1,
    )
    monkeypatch.setattr(gate, "staged_files", lambda _root: ["src/two.py"])
    worker_root = tmp_path / "worker-1"
    worker_ctx = WorktreeInvariantContext(
        session_id=worker_session,
        item_id=item_id,
        worktree_branch="task-1",
        expected_worktree_root=str(worker_root),
        actual_cwd=str(worker_root),
        is_inside_worktree=True,
    )
    assert (
        _decide(
            ctx=worker_ctx,
            repo_root=worker_root,
            conn=test_db,
            commit_message="",
        )[0]
        == 1
    )

    integration_ctx = WorktreeInvariantContext(
        session_id=worker_session,
        item_id=item_id,
        worktree_branch=f"integrate-{item_id}",
        expected_worktree_root=str(integration_path),
        actual_cwd=str(integration_path),
        is_inside_worktree=True,
    )
    monkeypatch.setattr(gate, "staged_files", lambda _root: ["src/done.py"])
    assert (
        _decide(
            ctx=integration_ctx,
            repo_root=integration_path,
            conn=test_db,
            commit_message="",
        )[0]
        == 0
    )
    monkeypatch.setattr(
        gate,
        "staged_files",
        lambda _root: ["src/stopped.py"],
    )
    assert (
        _decide(
            ctx=integration_ctx,
            repo_root=integration_path,
            conn=test_db,
            commit_message="",
        )[0]
        == 1
    )


def test_live_policy_resolution_error_returns_empty_coverage(
    test_db,
    tmp_path,
    monkeypatch,
) -> None:
    from yoke_core.domain import path_claim_task_bindings

    item_id, _lanes, _integration = _seed_lanes_and_claims(
        test_db,
        tmp_path,
    )
    session_id = "broken-policy"
    seed_session(
        test_db,
        session_id=session_id,
        item_id=item_id,
        task_num=1,
    )

    def _fail_policy(conn, item_id):
        raise RuntimeError("unreadable pin")

    monkeypatch.setattr(
        path_claim_task_bindings,
        "pinned_task_claim_policy",
        _fail_policy,
    )
    claim = resolve_active_claim_for_session(
        session_id=session_id,
        conn=test_db,
        target_path="src/one.py",
        cwd=str(tmp_path / "worker-1"),
    )

    assert claim is not None
    assert claim["covered_paths"] == []
