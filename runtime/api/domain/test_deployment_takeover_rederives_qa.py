"""Takeover carries only QA that ran; the successor re-derives everything else."""

from runtime.api.domain.deployment_qa_plan_groups_test_support import MEMBERS, RUN, _attach, _seed
from runtime.api.domain.deployment_qa_stage_execution_test_support import _plan, _seed_run, _stages
from runtime.api.domain.deployment_run_target_takeover_test_support import (
    ITEM_QA_STAGE, NEW, OLD, PASSED, WAITING, _close_passed, _contains, _memberless_copy,
    _seed_new, _seed_old, _take_over, record_case_verdict,
)
from yoke_core.domain.deployment_member_snapshot_write import write_member_snapshots
from yoke_core.domain.deployment_qa_plan_ownership import _snapshot, plan_owners
from yoke_core.domain.deployment_qa_stage_materialization import materialize_deployment_qa_stage
from yoke_core.domain.deployment_requirement_snapshots import requirement_selection
from yoke_core.domain.deployment_run_membership_removals import (
    clear_membership_removal, enrollment_removed_item_ids, membership_removals, record_membership_removals)
from yoke_core.domain.deployment_run_qa_transfer import transfer_qa_on
from yoke_core.domain.deployment_run_stage_entry import set_current_stage
from yoke_core.domain.qa_plan_management import replace_plan_cases

SUCCESSOR = "run-rederive-successor"
REMOVED = 9979


def _case(key, position):
    return {"case_key": key, "position": position, "method_id": "command", "target_envs": [],
            "instructions": f"run {key}", "expected_outcome": "it passes", "method_config": {"command": "true"}}


def _keys(pin):
    return sorted(case["case_key"] for case in pin["cases"])
def _member_row(conn, run_id):
    return conn.execute(
        "SELECT requirement_selection,requirement_snapshot FROM deployment_run_items "
        "WHERE run_id=%s AND item_id=%s", (run_id, WAITING)).fetchone()


def _taken_over(conn, monkeypatch):
    _close_passed(conn)
    _seed_new(conn)
    _contains(monkeypatch)
    assert _take_over(conn) == OLD


def test_plan_gaining_a_case_is_pinned_fresh_on_the_successor(test_db):
    """PLAT-391: materialized but unrun rows no longer pin the old case list."""
    shared, single = _seed(test_db), _plan(test_db, "single-smoke")
    _attach(test_db, MEMBERS[0], single)
    set_current_stage(test_db, RUN, "item-qa")
    materialize_deployment_qa_stage(test_db, deployment_run_id=RUN,
                                    deployment_stage="item-qa", deployment_member_item_id=MEMBERS[0])
    test_db.commit()
    assert _keys(_snapshot(test_db, RUN)["plan_groups"][str(single)]) == ["command-smoke"]
    replace_plan_cases(test_db, plan_id=single,
                       cases=[_case("command-smoke", 1), _case("prod-smoke", 2)])
    stages = _stages(shared)
    stages[1].pop("cases")
    _seed_run(test_db, run_id=SUCCESSOR, stages=stages, members=(), existing_members=MEMBERS)
    transfer_qa_on(test_db, old_id=RUN, new_id=SUCCESSOR, moving=set(MEMBERS))
    set_current_stage(test_db, SUCCESSOR, "item-qa")
    test_db.commit()
    assert plan_owners(test_db, SUCCESSOR)[single] == MEMBERS[0]
    pinned = _snapshot(test_db, SUCCESSOR)["plan_groups"][str(single)]
    assert _keys(pinned) == ["command-smoke", "prod-smoke"]


def test_requirement_waived_after_takeover_does_not_block_freeze(test_db, monkeypatch):
    """PLAT-403: a stored selection naming a since-waived requirement freezes."""
    cases = _seed_old(test_db, run_qa=False)
    owed = _memberless_copy(test_db, cases[WAITING])
    test_db.execute(
        "UPDATE qa_requirements SET deployment_run_id=NULL,deployment_stage=NULL,"
        "plan_id=NULL,item_id=%s,qa_phase='post_deploy' WHERE id=%s", (WAITING, owed))
    test_db.commit()
    _taken_over(test_db, monkeypatch)
    # Derived from live obligations through the admission helper, never copied.
    derived = _member_row(test_db, NEW)
    assert derived[0] is not None and derived[1] is not None
    test_db.execute("UPDATE qa_requirements SET waived_at=NOW() WHERE id=%s", (owed,))
    write_member_snapshots(test_db, NEW, {WAITING: requirement_selection(requirement_ids=(owed,))})
    assert '"requirements":[]' in _member_row(test_db, NEW)[1]


def test_operator_removal_on_predecessor_survives_takeover(test_db, monkeypatch):
    """PLAT-400: the successor's enrollment honors the predecessor's removal."""
    _seed_old(test_db, run_qa=False)
    record_membership_removals(test_db, OLD, [REMOVED], reason="operator removed it",
                               session_id=None, actor_id=1)
    _taken_over(test_db, monkeypatch)
    removed = {int(entry["item_id"]) for entry in membership_removals(test_db, OLD)}
    assert removed == {REMOVED, WAITING}
    # The takeover's own transfer entry for WAITING is not an operator removal.
    assert enrollment_removed_item_ids(test_db, NEW) == {REMOVED}
    # A later add-item on the successor clears the inherited removal.
    assert clear_membership_removal(test_db, NEW, REMOVED)
    assert enrollment_removed_item_ids(test_db, NEW) == frozenset()
    assert {int(entry["item_id"]) for entry in membership_removals(test_db, OLD)} == {WAITING}


def test_row_that_ran_keeps_its_verdict_on_the_successor(test_db, monkeypatch):
    cases = _seed_old(test_db, run_qa=False)
    record_case_verdict(test_db, cases[WAITING], "fail", evidence=True)
    _taken_over(test_db, monkeypatch)
    row = test_db.execute(
        "SELECT q.deployment_run_id,q.deployment_stage,r.verdict FROM qa_requirements q "
        "JOIN qa_runs r ON r.qa_requirement_id=q.id WHERE q.id=%s", (cases[WAITING],)).fetchone()
    assert (row[0], row[1], row[2]) == (NEW, ITEM_QA_STAGE, "fail")
    stayed = test_db.execute(
        "SELECT deployment_run_id FROM qa_requirements WHERE id=%s", (cases[PASSED],)).fetchone()
    assert stayed[0] == OLD
