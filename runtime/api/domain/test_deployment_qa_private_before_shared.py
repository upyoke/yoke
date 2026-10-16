"""Private member evidence progresses while a shared campaign is unfinished."""

import json
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_deployment_qa_shared_plans import (
    MEMBERS,
    RUN,
    _attach,
    _begin,
    _materialize,
    _seed,
)
from runtime.api.domain.test_deployment_qa_stage_execution import _complete_case, _plan
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_run_acceptance import item_qa_acceptance_blockers
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError


@pytest.mark.parametrize("shared_live", [False, True])
def test_private_progress_keeps_shared_acceptance_and_owner(
    test_db, shared_live, monkeypatch
):
    from runtime.api.tools import private_member_qa_probe

    def read_proof(argv, **kwargs):
        rows = test_db.execute(argv[3]).fetchall()
        return SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps(
                {"success": True, "result": {"rows": [list(row) for row in rows]}}
            ),
        )

    monkeypatch.setenv("DEPLOYMENT_RUN_ID", RUN)
    monkeypatch.setattr(private_member_qa_probe.subprocess, "run", read_proof)
    shared_plan = _seed(test_db)
    member = MEMBERS[1]
    private_plan = _plan(test_db, "independent-member-command")
    _attach(test_db, member, private_plan)
    for attaching_member in MEMBERS:
        _materialize(test_db, attaching_member)
    shared = _begin(test_db, MEMBERS[0]) if shared_live else None
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
        actor_id="2",
        session_id="private-owner",
    )
    assert execution["deployment_member_item_id"] == member
    assert execution["execution_target"]["deployment"]["member_item_id"] == member
    assert execution["deployment_run_id"] == RUN
    assert execution["deployment_stage"] == "item-qa"
    assert {row["plan_id"] for row in execution["roster"]} == {private_plan}
    # None ends the client partition loop after this private roster, rather
    # than implicitly asking the private owner to start the shared campaign.
    assert execution["remaining_requirement_count"] is None
    assert private_member_qa_probe.main() == 1
    private_requirement = _complete_case(test_db, execution)
    assert private_member_qa_probe.main() == 0
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id=%s AND verdict='pass'",
            (private_requirement,),
        ).fetchone()[0]
        == 1
    )
    for attaching_member in MEMBERS:
        assert not deployment_qa_stage_status(
            test_db, run_id=RUN, stage_name="item-qa", member_item_id=attaching_member
        )["accepted"]
        assert item_qa_acceptance_blockers(
            test_db, run_id=RUN, item_id=attaching_member
        )
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_runs r JOIN qa_requirements q "
            "ON q.id=r.qa_requirement_id WHERE q.deployment_run_id=%s AND q.plan_id=%s",
            (RUN, shared_plan),
        ).fetchone()[0]
        == 0
    )
    if shared_live:
        with pytest.raises(QaPlanExecutionStateError, match="owns the active"):
            begin_plan_execution(
                test_db,
                deployment_run_id=RUN,
                deployment_stage="item-qa",
                deployment_member_item_id=member,
                actor_id="2",
                session_id="private-owner",
            )
        assert _begin(test_db, member)["id"] == shared["id"]
    else:
        shared = _begin(test_db, member)
    assert shared["remaining_requirement_count"] == 0
    _complete_case(test_db, shared)
    for attaching_member in MEMBERS:
        assert deployment_qa_stage_status(
            test_db, run_id=RUN, stage_name="item-qa", member_item_id=attaching_member
        )["accepted"]
        assert not item_qa_acceptance_blockers(
            test_db, run_id=RUN, item_id=attaching_member
        )
