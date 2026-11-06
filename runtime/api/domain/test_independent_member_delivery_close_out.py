"""Final members close independently only when the flow has no shared QA."""

from __future__ import annotations

from runtime.api.domain.independent_member_delivery_close_out_test_support import (
    MEMBER_A as MEMBER_A,
    MEMBER_B as MEMBER_B,
    _seed_final_run as _seed_final_run,
    _settle as _settle,
    _status as _status,
)


from typing import Any

import pytest

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    HOLDER_A,
    HOLDER_B,
    _recipients,
)
from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)
from yoke_core.domain.deployment_delivery_close_out_notice import (
    notify_delivery_cleared,
)
from yoke_core.domain.deployment_member_independent_close_out import (
    independent_member_delivery_ready,
)
from yoke_core.domain.deployment_qa_member_acceptance_notice import (
    item_qa_accepted_idempotency_key,
    notify_item_qa_accepted,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_resume import (
    prior_deployment_qa_refusals,
)
from yoke_core.domain.deployment_run_completion_preconditions import refuse_succeeded


def test_one_member_closes_while_sibling_qa_blocks_the_run(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    run_id = "run-independent-members"
    _seed_final_run(test_db, run_id, shared_qa=False)
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER_B,
    )

    _settle(test_db, run_id=run_id, stage="item-qa", member=MEMBER_A)

    assert independent_member_delivery_ready(test_db, item_id=MEMBER_A, run_id=run_id)
    assert _status(test_db, MEMBER_A) == "done"
    assert test_db.execute("SELECT deployed_to FROM items WHERE id=%s", (MEMBER_A,)).fetchone()[0] == "prod"
    from yoke_core.domain.dependency_satisfaction import evaluate_persisted_satisfaction
    from yoke_core.domain.workflow_runtime import load_item_workflow_runtime

    assert evaluate_persisted_satisfaction(
        test_db, blocking_item_id=MEMBER_A, satisfaction="fact:deployed:prod",
        blocking_status="done", workflow=load_item_workflow_runtime(test_db, MEMBER_A),
    ).satisfied
    assert _status(test_db, MEMBER_B) == "release"
    assert (
        test_db.execute(
            "SELECT status FROM deployment_runs WHERE id=%s", (run_id,)
        ).fetchone()["status"]
        == "executing"
    )
    assert (
        test_db.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id=%s", (HOLDER_A,)
        ).fetchone()["ended_at"]
        is not None
    )
    assert (
        test_db.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id=%s", (HOLDER_B,)
        ).fetchone()["ended_at"]
        is None
    )
    assert (
        _recipients(test_db, item_qa_accepted_idempotency_key(MEMBER_A, run_id)) == []
    )
    assert refuse_succeeded(test_db, run_id) is not None

    assert notify_item_qa_accepted(test_db, run_id=run_id, item_id=MEMBER_A) == ""
    assert _status(test_db, MEMBER_A) == "done"
    _settle(test_db, run_id=run_id, stage="item-qa", member=MEMBER_B)
    assert _status(test_db, MEMBER_B) == "done"
    assert (
        test_db.execute(
            "SELECT status FROM deployment_runs WHERE id=%s", (run_id,)
        ).fetchone()["status"]
        == "executing"
    )
    test_db.execute(
        "UPDATE deployment_runs SET status='succeeded',current_stage='complete' "
        "WHERE id=%s",
        (run_id,),
    )
    test_db.commit()
    assert notify_delivery_cleared(test_db, run_id=run_id) == []
    assert (_status(test_db, MEMBER_A), _status(test_db, MEMBER_B)) == ("done", "done")


def test_shared_run_qa_keeps_both_members_open_until_run_success(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    run_id = "run-shared-review"
    stages = _seed_final_run(test_db, run_id, shared_qa=True)
    _settle(test_db, run_id=run_id, stage="item-qa", member=MEMBER_A)

    assert _status(test_db, MEMBER_A) == "release"
    assert _status(test_db, MEMBER_B) == "release"
    assert not independent_member_delivery_ready(
        test_db, item_id=MEMBER_A, run_id=run_id
    )
    assert prior_deployment_qa_refusals(
        test_db, run_id=run_id, stages=stages, start_stage="run-qa"
    )
    test_db.execute(
        "UPDATE deployment_runs SET current_stage='run-qa' WHERE id=%s", (run_id,)
    )
    test_db.commit()
    with pytest.raises(ValueError, match="prior scoped QA acceptance"):
        materialize_deployment_qa_stage(
            test_db, deployment_run_id=run_id, deployment_stage="run-qa"
        )

    test_db.execute(
        "UPDATE deployment_runs SET current_stage='item-qa' WHERE id=%s", (run_id,)
    )
    test_db.commit()
    _settle(test_db, run_id=run_id, stage="item-qa", member=MEMBER_B)
    assert (_status(test_db, MEMBER_A), _status(test_db, MEMBER_B)) == (
        "release",
        "release",
    )
    test_db.execute(
        "UPDATE deployment_runs SET current_stage='run-qa' WHERE id=%s", (run_id,)
    )
    test_db.commit()
    _settle(test_db, run_id=run_id, stage="run-qa", member=None)
    assert (_status(test_db, MEMBER_A), _status(test_db, MEMBER_B)) == (
        "release",
        "release",
    )

    test_db.execute(
        "UPDATE deployment_runs SET status='succeeded',current_stage='complete' "
        "WHERE id=%s",
        (run_id,),
    )
    test_db.commit()
    assert {
        row["delivery"] for row in notify_delivery_cleared(test_db, run_id=run_id)
    } == {"closed"}
    assert (_status(test_db, MEMBER_A), _status(test_db, MEMBER_B)) == ("done", "done")


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_terminal_failed_delivery_cannot_close_member(
    test_db: Any, monkeypatch, status: str
) -> None:
    _isolate_status_effects(monkeypatch)
    run_id = f"run-{status}-delivery"
    _seed_final_run(test_db, run_id, shared_qa=False)
    test_db.execute(
        "UPDATE deployment_runs SET status=%s WHERE id=%s", (status, run_id)
    )
    test_db.commit()

    assert not independent_member_delivery_ready(
        test_db, item_id=MEMBER_A, run_id=run_id
    )
    assert notify_item_qa_accepted(test_db, run_id=run_id, item_id=MEMBER_A) == ""
    assert _status(test_db, MEMBER_A) == "release"
