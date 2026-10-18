"""Task amendment retires a task and its bindings, not item-owned claims."""

import pytest

from runtime.api.domain.path_claim_task_test_support import (
    bind_claim,
    seed_epic,
    seed_item_claim,
    seed_target,
    seed_worker_task,
)
from yoke_core.domain.epic_amend import task_remove, task_split


@pytest.mark.parametrize("operation", ["remove", "split"])
def test_amend_retires_parent_scope_and_preserves_item_claim(
    test_db, tmp_path, operation
):
    item_id = seed_epic(test_db, item_id=21101)
    seed_worker_task(
        test_db,
        item_id=item_id,
        task_num=1,
        lane_path=tmp_path / "worker",
        budget_path="src/parent.py",
    )
    target_id = seed_target(test_db, item_id=item_id, path="src/parent.py")
    claim_id = seed_item_claim(
        test_db,
        item_id=item_id,
        target_ids=(target_id,),
        state="planned",
    )
    bind_claim(test_db, claim_id=claim_id, item_id=item_id, task_num=1)
    if operation == "remove":
        task_remove(test_db, item_id, 1)
    else:
        result = task_split(
            test_db, item_id, 1, [{"title": "First"}, {"title": "Second"}]
        )
        assert len(result.new_task_nums) == 2
        assert (
            test_db.execute(
                "SELECT COUNT(*) FROM epic_tasks WHERE epic_id=%s",
                (item_id,),
            ).fetchone()[0]
            == 2
        )
    assert (
        test_db.execute(
            "SELECT 1 FROM epic_tasks WHERE epic_id=%s AND task_num=1",
            (item_id,),
        ).fetchone()
        is None
    )
    assert (
        test_db.execute(
            "SELECT 1 FROM path_claim_task_bindings WHERE claim_id=%s",
            (claim_id,),
        ).fetchone()
        is None
    )
    assert test_db.execute(
        "SELECT 1 FROM path_claims WHERE id=%s", (claim_id,)
    ).fetchone()
