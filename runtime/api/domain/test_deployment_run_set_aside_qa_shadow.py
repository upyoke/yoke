"""Historical set-aside QA never duplicates a case a live release already owns."""

from runtime.api.domain.deployment_run_target_takeover_test_support import (
    _seed_old, _contains, _members, _memberless_copy,
    OLD, WAITING, DRIVER_SESSION,
)
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE, record_case_verdict,
)
from yoke_core.domain.deployment_run_member_admission import MemberAdmission, admit_run_items
from yoke_core.domain.deployment_run_member_set_aside import SET_ASIDE_REASON
from yoke_core.domain.deployment_run_target_takeover import take_over_waiting_run
from yoke_core.domain.qa_plan_execution_begin import begin_plan_execution
from yoke_core.domain.qa_plan_execution_store import select_plan_execution

HISTORICAL = "run-shadow-historical"
BEHIND = "run-shadow-behind"
TAKER = "run-shadow-taker"


def _run_copy(conn, run_id, *, status, created_at, lineage, removals=None):
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,target_tier,target_environment_id,"
        "release_lineage,status,created_at,membership_removals) "
        "SELECT %s,project_id,flow,target_tier,target_environment_id,%s,%s,%s,%s "
        "FROM deployment_runs WHERE id=%s",
        (run_id, lineage, status, created_at, removals, OLD),
    )


def _historical_case(conn, canonical, *, case_key=None):
    """An older copy of WAITING's case, kept by a rework removal on HISTORICAL."""
    copy = _memberless_copy(conn, canonical)
    conn.execute(
        "UPDATE qa_requirements SET deployment_run_id=%s,deployment_member_item_id=%s,"
        "plan_case_key=COALESCE(%s,plan_case_key) WHERE id=%s",
        (HISTORICAL, WAITING, case_key, copy),
    )
    return copy


def _owner(conn, requirement_id):
    row = conn.execute(
        "SELECT deployment_run_id,retracted_at FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()
    return row["deployment_run_id"], row["retracted_at"]


def _verdicts(conn, requirement_id):
    return [row[0] for row in conn.execute(
        "SELECT verdict FROM qa_runs WHERE qa_requirement_id=%s ORDER BY id",
        (requirement_id,),
    ).fetchall()]


def test_historical_case_stays_home_when_a_live_release_owns_its_identity(test_db, monkeypatch):
    cases = _seed_old(test_db, run_qa=False)
    canonical = cases[WAITING]
    # The active release is deploying while a later run is created behind it.
    test_db.execute(
        "UPDATE deployment_runs SET current_stage='deploy',created_at='2026-11-26T00:00:00Z' "
        "WHERE id=%s", (OLD,))
    removal = ('[{"item_id":%d,"reason":"%s","removed_at":"2026-11-25T04:00:00Z",'
               '"session_id":null,"actor_id":null}]' % (WAITING, SET_ASIDE_REASON))
    _run_copy(test_db, HISTORICAL, status="cancelled", created_at="2026-11-25T00:00:00Z",
              lineage="a" * 40, removals=removal)
    test_db.commit()
    shadowed = _historical_case(test_db, canonical)
    distinct = _historical_case(test_db, canonical, case_key="historical-only-case")
    test_db.commit()
    record_case_verdict(test_db, shadowed, "fail", evidence=True)
    record_case_verdict(test_db, distinct, "pass", evidence=True)

    _run_copy(test_db, BEHIND, status="created", created_at="2026-11-27T00:00:00Z",
              lineage="c" * 40)
    admit_run_items(test_db, run_id=BEHIND, members=(MemberAdmission(WAITING),))
    test_db.commit()
    assert _owner(test_db, shadowed) == (HISTORICAL, None)
    assert _owner(test_db, distinct) == (BEHIND, None)
    assert _owner(test_db, canonical) == (OLD, None)

    # Item QA opens on the active release; its walk is live evidence.
    test_db.execute("UPDATE deployment_runs SET current_stage=%s WHERE id=%s",
                    (ITEM_QA_STAGE, OLD))
    test_db.commit()
    execution = begin_plan_execution(test_db, deployment_run_id=OLD,
        deployment_stage=ITEM_QA_STAGE, deployment_member_item_id=WAITING,
        actor_id="1", session_id=DRIVER_SESSION)
    before = select_plan_execution(test_db, execution["id"], lock=False)

    _run_copy(test_db, TAKER, status="created", created_at="2026-11-27T01:00:00Z",
              lineage="d" * 40)
    test_db.commit()
    _contains(monkeypatch)
    assert take_over_waiting_run(test_db, TAKER, session_id=DRIVER_SESSION, actor_id=1) == OLD
    test_db.commit()

    assert WAITING in _members(test_db, TAKER)
    assert _owner(test_db, canonical) == (TAKER, None)
    assert select_plan_execution(test_db, execution["id"], lock=False) == {
        **before, "deployment_run_id": TAKER}
    assert _owner(test_db, distinct) == (TAKER, None)
    assert _verdicts(test_db, distinct) == ["pass"]
    assert _owner(test_db, shadowed) == (HISTORICAL, None)
    assert _verdicts(test_db, shadowed) == ["fail"]
