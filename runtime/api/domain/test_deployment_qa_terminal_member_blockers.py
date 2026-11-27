"""A member closed after takeover owes the successor run no active QA.

Takeover carries a member whose older-run pass is not yet closed into the
successor, rebinding its requirement there. When that older pass then closes
the item before the successor's dispatch, the item's work is done: dispatch
already skips it, and the readers that answer "what is still outstanding"
must agree. Its frozen row, older target and prior pass stay readable; an
unfinished member and the run-level check keep blocking.
"""

from __future__ import annotations

from runtime.api.domain.deployment_run_target_takeover_test_support import (
    ITEM_QA_STAGE,
    NEW,
    NEW_LINEAGE,
    OLD,
    PASSED,
    RUN_QA_STAGE,
    WAITING,
    _contains,
    _memberless_copy,
    _members,
    _seed_new,
    _seed_old,
    _take_over,
)
from yoke_core.domain.deployment_stage_receipts import (
    allocate_deployment_stage_receipt,
    complete_deployment_stage_receipt,
)
from yoke_core.domain.deployment_qa_run_acceptance import (
    current_item_qa,
    member_qa_standings,
)
from yoke_core.domain.deploy_target_occupancy import open_qa_lines
from yoke_core.domain.deployment_qa_stage_outstanding import qa_stage_outstanding


def _closed_after_takeover(conn, monkeypatch) -> dict[int, int]:
    cases = _seed_old(conn, run_qa=True)
    _memberless_copy(conn, cases[WAITING], stage=RUN_QA_STAGE)
    _seed_new(conn)
    _contains(monkeypatch)
    _take_over(conn)
    # The successor arrives at item QA with its own frozen composition.
    conn.execute(
        "UPDATE deployment_runs n SET status='executing',current_stage=%s,"
        "composition_frozen_at=now(),requirement_snapshot=o.requirement_snapshot "
        "FROM deployment_runs o WHERE n.id=%s AND o.id=%s",
        ("deploy", NEW, OLD),
    )
    # Its own deploy is ready on a newer lineage, so the carried requirement
    # still names the older run's target.
    receipt = allocate_deployment_stage_receipt(
        conn,
        run_id=NEW,
        stage_name="deploy",
        correlation_id="successor-deploy",
        target_kind="persistent_environment",
        executor="test",
        commit=False,
    )
    complete_deployment_stage_receipt(
        conn,
        run_id=NEW,
        receipt_id=receipt["id"],
        correlation_id=receipt["correlation_id"],
        status="ready",
        target_name="stage",
        observed_url="https://preview.example.test",
        observed_release_lineage=NEW_LINEAGE,
        executor_receipt="test://successor",
        commit=False,
    )
    conn.execute(
        "UPDATE deployment_runs SET current_stage=%s WHERE id=%s", (ITEM_QA_STAGE, NEW)
    )
    conn.execute("UPDATE items SET status='done' WHERE id=%s", (PASSED,))
    conn.commit()
    return cases


def _pass(conn, requirement_id: int):
    return conn.execute(
        "SELECT r.deployment_run_id,r.deployment_member_item_id,"
        "r.execution_target_digest,r.rebound_from_target_json,"
        "(SELECT count(*) FROM qa_runs q WHERE q.qa_requirement_id=r.id "
        "AND q.verdict='pass') AS passes FROM qa_requirements r WHERE r.id=%s",
        (requirement_id,),
    ).fetchone()


def test_a_member_closed_after_takeover_leaves_active_blockers(
    test_db, monkeypatch
):
    cases = _closed_after_takeover(test_db, monkeypatch)
    before = dict(_pass(test_db, cases[PASSED]))

    item = qa_stage_outstanding(test_db, run_id=NEW, stage_name=ITEM_QA_STAGE)
    assert item is not None
    assert PASSED not in item.waiting_members
    assert WAITING in item.waiting_members
    assert item.subjects == 2
    assert current_item_qa(
        test_db, run_id=NEW, item_id=PASSED, current_stage=ITEM_QA_STAGE
    ) is None
    standings = member_qa_standings(
        test_db, [(NEW, PASSED, ITEM_QA_STAGE), (NEW, WAITING, ITEM_QA_STAGE)]
    )
    assert (NEW, PASSED) not in standings
    assert standings[(NEW, WAITING)]["state"] != "accepted"

    run = qa_stage_outstanding(test_db, run_id=NEW, stage_name=RUN_QA_STAGE)
    assert run is not None and run.waiting_members == (None,)

    # The member stays, with its frozen row, older target and prior pass.
    assert _members(test_db, NEW) == {PASSED, WAITING}
    assert dict(_pass(test_db, cases[PASSED])) == before
    assert before["passes"] == 1

    # Target occupancy reads the same walk: only the open member holds it.
    held = " ".join(open_qa_lines(test_db, NEW))
    assert f"YOK-{WAITING}" in held and f"YOK-{PASSED}" not in held
