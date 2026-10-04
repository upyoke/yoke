"""Source QA credit must not wait for the run that waits for member close-out."""

from __future__ import annotations

import pytest

from runtime.api.domain.test_dash_post_deploy_done_consumption import _accept_member_qa
from runtime.api.domain.test_done_gate_admitted_copy_multiplicity import _deliver_intake
from runtime.api.domain.test_post_deploy_original_pass_needs_admission import (
    _record_evidence,
)
from runtime.api.fixtures.backlog import insert_qa_run
from yoke_core.domain.deployment_run_collective_finalization import mark_settling
from yoke_core.domain.deployment_qa_source_obligation import source_obligation_consumed
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)


@pytest.mark.parametrize("status", ("executing", "failed", "cancelled"))
@pytest.mark.parametrize("accepted", (True, False))
def test_settling_requires_accepted_source_qa_and_a_live_run(test_db, status, accepted):
    item_id = 9891
    run_id = "run-source-settlement"
    source_id = _deliver_intake(test_db, item_id=item_id, run_id=run_id)
    if accepted:
        _accept_member_qa(test_db, run_id=run_id, item_id=item_id)
    else:
        copy = materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=run_id,
            deployment_stage="member-qa",
            deployment_member_item_id=item_id,
        )
        insert_qa_run(
            test_db,
            qa_requirement_id=copy["created_requirement_ids"][0],
            verdict="fail",
        )
    test_db.execute(
        "UPDATE deployment_runs SET status='executing' WHERE id=%s", (run_id,)
    )
    test_db.commit()
    mark_settling(test_db, run_id)
    test_db.execute(
        "UPDATE deployment_runs SET status=%s WHERE id=%s", (status, run_id)
    )
    test_db.commit()

    assert source_obligation_consumed(
        test_db,
        item_id=item_id,
        source_requirement_id=source_id,
    ) is (accepted and status == "executing")


def test_accepted_source_closes_the_member_before_run_success(test_db, monkeypatch):
    from runtime.api.domain.test_status_transition_preflight import (
        _isolate_status_effects,
    )
    from yoke_core.domain.deployment_runs_crud_mutate import cmd_update

    _isolate_status_effects(monkeypatch)
    item_id = 9892
    run_id = "run-source-closes"
    source_id = _deliver_intake(test_db, item_id=item_id, run_id=run_id)
    _accept_member_qa(test_db, run_id=run_id, item_id=item_id)
    _record_evidence(test_db, item_id=item_id)
    test_db.execute(
        "UPDATE deployment_runs SET status='executing' WHERE id=%s", (run_id,)
    )
    test_db.commit()

    assert cmd_update(run_id, "status", "succeeded") is None
    assert source_obligation_consumed(
        test_db, item_id=item_id, source_requirement_id=source_id
    )
    assert (
        test_db.execute("SELECT status FROM items WHERE id=%s", (item_id,)).fetchone()[
            0
        ]
        == "done"
    )
