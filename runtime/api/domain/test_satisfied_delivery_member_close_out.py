"""Passed or waived member QA closes on delivery without another wake."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.test_deployment_delivery_close_out_notice import (
    COMPLETION_FLOW,
    _project,
    _run,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    _recipients,
)
from runtime.api.domain.test_no_obligation_member_close_out import _ready_member
from runtime.api.domain.test_status_transition_preflight import (
    _isolate_status_effects,
)
from runtime.api.fixtures.backlog_inserts import insert_qa_requirement, insert_qa_run
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_delivery_close_out_notice import (
    delivery_cleared_idempotency_key,
    notify_delivery_cleared,
)


SATISFIED_QA_ITEM = 9827


def _settled_member_requirement(
    conn: Any, *, item_id: int, run_id: str, resolution: str
) -> None:
    requirement = insert_qa_requirement(
        conn,
        item_id=None,
        deployment_run_id=run_id,
        deployment_member_item_id=item_id,
        deployment_stage="item-qa",
        qa_kind="plan_case",
        qa_phase="post_deploy",
        blocking_mode="blocking",
        **(
            {
                "waived_at": iso8601_now(),
                "waiver_rationale": "operator accepted the waiver",
                "waiver_source": "owner",
            }
            if resolution == "waive"
            else {}
        ),
    )
    if resolution == "pass":
        insert_qa_run(
            conn,
            qa_requirement_id=int(requirement["id"]),
            qa_kind="plan_case",
            verdict="pass",
        )


@pytest.mark.parametrize("resolution", ["pass", "waive"])
def test_satisfied_member_qa_closes_without_a_delivery_wake(
    test_db: Any, monkeypatch, resolution: str
) -> None:
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _ready_member(test_db, SATISFIED_QA_ITEM, HOLDER_A)
    run_id = f"run-satisfied-{resolution}"
    _run(
        test_db,
        run_id,
        flow=COMPLETION_FLOW,
        members=(SATISFIED_QA_ITEM,),
    )
    _settled_member_requirement(
        test_db,
        item_id=SATISFIED_QA_ITEM,
        run_id=run_id,
        resolution=resolution,
    )

    [report] = notify_delivery_cleared(test_db, run_id=run_id)

    assert report["delivery"] == "closed"
    key = delivery_cleared_idempotency_key(SATISFIED_QA_ITEM, run_id)
    assert _recipients(test_db, key) == []
    status = test_db.execute(
        "SELECT status FROM items WHERE id=%s", (SATISFIED_QA_ITEM,)
    ).fetchone()["status"]
    assert status == "done"
    holder = test_db.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id=%s", (HOLDER_A,)
    ).fetchone()
    assert holder is not None and holder["ended_at"] is not None
