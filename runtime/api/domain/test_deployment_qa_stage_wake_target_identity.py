"""The wake key's ``target_digest`` component, delivered for real.

Split out of ``test_deployment_qa_stage_wake_delivery.py``, which owns the
shared claim/session/message helpers this file reuses, to stay under the
authored line budget.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    PROJECT_YOKE,
    _bodies,
    _claim,
    _project,
    _recipients,
    insert_item,
    seed_session,
)
from yoke_core.domain.deployment_qa_stage_wake import (
    notify_item_scoped_qa_wait,
    stage_wait_idempotency_key,
)
from yoke_core.domain.work_claim_targets import make_item_target


def test_a_distinct_pinned_target_within_one_run_gets_its_own_fresh_notice(
    test_db: Any,
) -> None:
    """The wake key folds in the stage's own target_digest, not just
    (run, stage, item): a distinct pinned target within the SAME run's
    existing retry/requirement contract still gets a fresh notice instead
    of being absorbed by an earlier target's already-delivered one. This
    is not a route for swapping a frozen run's candidate or membership in
    place -- that stays a replacement run's job; it only keeps two
    genuinely different waits from sharing one message."""
    _project(test_db)
    item_id = 9706
    insert_item(test_db, id=item_id, project_sequence=item_id, workflow_id="issue")
    seed_session(test_db, HOLDER_A)
    _claim(
        test_db,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(item_id).scope_json(),
    )

    target_1_key = stage_wait_idempotency_key(
        "run-attempts", "item-qa", item_id, "digest-1"
    )
    target_2_key = stage_wait_idempotency_key(
        "run-attempts", "item-qa", item_id, "digest-2"
    )

    notify_item_scoped_qa_wait(
        test_db,
        run_id="run-attempts",
        stage_name="item-qa",
        item_id=item_id,
        project_id=PROJECT_YOKE,
        reasons="target 1 evidence still missing",
        target_digest="digest-1",
    )
    notify_item_scoped_qa_wait(
        test_db,
        run_id="run-attempts",
        stage_name="item-qa",
        item_id=item_id,
        project_id=PROJECT_YOKE,
        reasons="target 2 evidence still missing",
        target_digest="digest-2",
    )

    assert _recipients(test_db, target_1_key) == [HOLDER_A]
    assert _recipients(test_db, target_2_key) == [HOLDER_A]
    [body_1] = _bodies(test_db, target_1_key)
    [body_2] = _bodies(test_db, target_2_key)
    assert "target 1 evidence still missing" in body_1
    assert "target 2 evidence still missing" in body_2
