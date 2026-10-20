"""Rework coverage for a per-task Epic whose earlier tasks already landed."""

from __future__ import annotations

from runtime.api.domain.path_claim_task_test_support import (
    bind_claim,
    seed_epic,
    seed_item_claim,
    seed_target,
    seed_worker_task,
)
from runtime.api.domain._path_claims_test_helpers import local_human
from yoke_core.domain.advance_path_claim_task_activation import (
    task_activation_block_reason,
)
from yoke_core.domain.path_claim_task_coverage import evaluate_task_coverage
from yoke_core.domain.path_claim_task_registration import register_for_task
from yoke_core.domain.path_claims_landing import (
    needs_rework_coverage,
    release_landed_claims,
)


def _land_tasks(conn, tmp_path, *, item_id: int, task_nums: tuple[int, ...]) -> None:
    """Seed bound, active task coverage, then release it the way landing does."""
    for task_num in task_nums:
        path = f"src/task_{task_num}.py"
        seed_worker_task(
            conn,
            item_id=item_id,
            task_num=task_num,
            lane_path=tmp_path / f"task-{task_num}",
            task_status="done",
            budget_path=path,
        )
        claim_id = seed_item_claim(
            conn,
            item_id=item_id,
            target_ids=(seed_target(conn, item_id=item_id, path=path),),
        )
        bind_claim(conn, claim_id=claim_id, item_id=item_id, task_num=task_num)
    release_landed_claims(conn, item_id=item_id)
    conn.commit()


def test_landed_epic_reworks_with_a_narrow_task_claim(test_db, tmp_path) -> None:
    item_id = seed_epic(test_db, item_id=21101)
    _land_tasks(test_db, tmp_path, item_id=item_id, task_nums=(1, 2, 3))
    assert needs_rework_coverage(test_db, item_id)

    claim_id = register_for_task(
        test_db,
        item_id=item_id,
        task_num=2,
        integration_target="main",
        paths=["src/fix.py"],
        actor_id=local_human(test_db),
        allow_planned=True,
    )

    result = evaluate_task_coverage(test_db, item_id)
    assert result.verdict == "pass"
    assert result.satisfying_claims == (claim_id,)
    assert task_activation_block_reason(test_db, item_id) is None
    assert not needs_rework_coverage(test_db, item_id)


def test_unlanded_task_still_requires_full_coverage(test_db, tmp_path) -> None:
    item_id = seed_epic(test_db, item_id=21102)
    _land_tasks(test_db, tmp_path, item_id=item_id, task_nums=(1,))
    seed_worker_task(
        test_db,
        item_id=item_id,
        task_num=2,
        lane_path=tmp_path / "task-2",
        budget_path="src/new.py",
    )

    result = evaluate_task_coverage(test_db, item_id)
    assert result.verdict == "block"
    assert result.missing_tasks == (2,)
    assert result.uncovered_paths == ("src/new.py",)

    register_for_task(
        test_db,
        item_id=item_id,
        task_num=2,
        integration_target="main",
        paths=["src/other.py"],
        actor_id=local_human(test_db),
        allow_planned=True,
    )
    result = evaluate_task_coverage(test_db, item_id)
    assert result.verdict == "block"
    assert result.partial_tasks == (2,)
    assert task_activation_block_reason(test_db, item_id) == result.reason
