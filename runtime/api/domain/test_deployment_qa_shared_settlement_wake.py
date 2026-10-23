"""Settlement wakes the execution's waiters, not every blocked member."""

from runtime.api.domain.test_deployment_qa_shared_plans import (
    MEMBERS,
    RUN,
    _attach,
    _materialize,
)
from runtime.api.domain.test_deployment_qa_shared_wait import (
    _begin,
    _holders,
    _notices,
    _seed,
)
from runtime.api.domain.test_deployment_qa_stage_execution import _complete_case, _plan
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.qa_plan_execution_state import finish_plan_execution


def test_settlement_wakes_only_the_execution_s_waiters(test_db):
    _seed(test_db)
    _holders(test_db)
    other = _plan(test_db, "other-shared")
    for member in MEMBERS:
        _attach(test_db, member, other)
        _materialize(test_db, member)
    held = _begin(test_db, MEMBERS[0], "member-9901")
    _begin(test_db, MEMBERS[1], "member-9902", plan="other-shared")
    finish_plan_execution(test_db, held, state="aborted", reason="stop shared walk")
    assert {row["session_id"] for row in _notices(test_db, held)} == {"member-9901"}


def test_manual_gated_member_is_not_sent_run_now(test_db):
    _seed(test_db)
    _holders(test_db)
    for member in MEMBERS:
        _materialize(test_db, member)
    test_db.execute(
        "INSERT INTO qa_requirements(deployment_run_id,deployment_stage,"
        "deployment_member_item_id,qa_kind,qa_phase,blocking_mode,requirement_source,"
        "method_id,plan_case_key,wake_path,wake_evidence,created_at) VALUES "
        "(%s,'item-qa',%s,'plan_case','post_deploy','blocking','flow_derived',"
        "'exploratory-mission','real-traffic','manual','traffic exists',"
        "'2026-10-14T00:00:00Z')",
        (RUN, MEMBERS[1]),
    )
    test_db.commit()
    execution = _begin(test_db, MEMBERS[0], "member-9901")
    _complete_case(test_db, execution)
    assert _notices(test_db, execution) == []
    assert not deployment_qa_stage_status(
        test_db, run_id=RUN, stage_name="item-qa", member_item_id=MEMBERS[1]
    )["accepted"]
