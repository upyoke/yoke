"""Successor QA reuses inherited obligations without changing verdict history."""

import pytest

from runtime.api.domain.test_deployment_qa_takeover_identity import _execution
from runtime.api.domain.test_deployment_qa_takeover_identity import _group_execution
from runtime.api.domain import test_deployment_run_target_takeover as takeover
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import record_case_verdict
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)


@pytest.mark.parametrize("verdict", ["pass", "fail"])
def test_successor_materialization_keeps_original_requirement_and_verdict(
    test_db, monkeypatch, verdict
):
    execution = _execution(test_db, monkeypatch)
    requirement = execution["roster"][0]["requirement_id"]
    attempt = record_case_verdict(test_db, requirement, verdict, evidence=True)
    before = dict(
        test_db.execute(
            "SELECT * FROM qa_requirements WHERE id=%s",
            (requirement,),
        ).fetchone()
    )
    # Model arrival at the successor's QA stage; it owns a separate frozen
    # composition while its moved obligations retain their original snapshots.
    test_db.execute(
        "UPDATE deployment_runs n SET status='executing',current_stage=%s,"
        "composition_frozen_at=now(),requirement_snapshot=o.requirement_snapshot "
        "FROM deployment_runs o WHERE n.id=%s AND o.id=%s",
        (takeover.RUN_QA_STAGE, takeover.NEW, takeover.OLD),
    )
    result = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=takeover.NEW,
        deployment_stage=takeover.RUN_QA_STAGE,
    )
    assert result["created_requirement_ids"] == []
    assert result["existing_requirement_ids"] == [requirement]
    assert (
        dict(
            test_db.execute(
                "SELECT * FROM qa_requirements WHERE id=%s",
                (requirement,),
            ).fetchone()
        )
        == before
    )
    assert (
        test_db.execute(
            "SELECT verdict FROM qa_runs WHERE id=%s",
            (attempt,),
        ).fetchone()[0]
        == verdict
    )


def test_successor_reuses_the_moved_group_instead_of_forming_another(
    test_db, monkeypatch
):
    from runtime.api.domain import test_deployment_qa_plan_groups as shared
    from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
    from yoke_core.domain.deployment_qa_plan_groups import run_groups

    execution = _group_execution(test_db, monkeypatch)
    requirement = execution["roster"][0]["requirement_id"]
    test_db.execute(
        "UPDATE deployment_runs n SET status='executing',current_stage='item-qa',"
        "composition_frozen_at=now(),requirement_snapshot=o.requirement_snapshot "
        "FROM deployment_runs o WHERE n.id=%s AND o.id=%s",
        (takeover.NEW, shared.RUN),
    )
    assert ensure_groups(test_db, takeover.NEW, "item-qa") == []
    (group,) = run_groups(test_db, [takeover.NEW], "item-qa")
    assert group.open and group.requirement_ids == (requirement,)
    assert run_groups(test_db, [shared.RUN], "item-qa") == []
