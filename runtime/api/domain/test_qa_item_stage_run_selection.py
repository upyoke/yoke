"""Item QA resolves to the live run holding the member's open stage rows.

Seeded on real runs: OLD stands on item QA with PASSED's case passed and
WAITING's case open (``deployment_run_target_takeover_test_support``).
"""

from __future__ import annotations

import pytest

from runtime.api.domain.deployment_run_target_takeover_test_support import (
    ITEM_QA_STAGE,
    NEW,
    OLD,
    PASSED,
    WAITING,
    _contains,
    _memberless_copy,
    _requirement,
    _seed_new,
    _seed_old,
    _take_over,
)
from yoke_core.domain.qa_item_stage_run_selection import (
    QaItemRunNotMember,
    QaItemStageAmbiguous,
    QaItemStageUnavailable,
    open_stage_holds,
    select_stage_run,
)

PRODUCTION = "run-selection-production"


def _select(conn, item_id, **kwargs):
    return select_stage_run(
        conn, item_id=item_id, stage=ITEM_QA_STAGE, item_ref=f"YOK-{item_id}", **kwargs
    )


def _sibling_holding(conn, run_id, item_id, requirement_id, *, stage=ITEM_QA_STAGE):
    """A second live run of the same target holding a copy of the member's case."""
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,target_tier,"
        "target_environment_id,release_lineage,status,current_stage,created_at) "
        "SELECT %s,project_id,flow,target_tier,target_environment_id,release_lineage,"
        "'executing',%s,created_at + interval '1 minute' FROM deployment_runs WHERE id=%s",
        (run_id, stage, OLD),
    )
    conn.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) "
        "SELECT %s,%s,created_at FROM deployment_runs WHERE id=%s",
        (run_id, item_id, run_id),
    )
    copy = _memberless_copy(conn, requirement_id)
    conn.execute(
        "UPDATE qa_requirements SET deployment_run_id=%s,deployment_member_item_id=%s "
        "WHERE id=%s",
        (run_id, item_id, copy),
    )
    conn.commit()
    return copy


def test_open_rows_name_the_run_and_passed_rows_do_not(test_db):
    cases = _seed_old(test_db, run_qa=False)
    [hold] = open_stage_holds(test_db, item_id=WAITING, stage=ITEM_QA_STAGE)
    assert (hold.run_id, hold.requirement_ids) == (OLD, (cases[WAITING],))
    assert open_stage_holds(test_db, item_id=PASSED, stage=ITEM_QA_STAGE) == []
    assert _select(test_db, WAITING) == OLD


@pytest.mark.parametrize("column", ["waived_at", "superseded_at", "retracted_at"])
def test_settled_rows_do_not_hold_the_run(test_db, column):
    cases = _seed_old(test_db, run_qa=False)
    test_db.execute(
        f"UPDATE qa_requirements SET {column}=now() WHERE id=%s", (cases[WAITING],)
    )
    test_db.commit()
    assert open_stage_holds(test_db, item_id=WAITING, stage=ITEM_QA_STAGE) == []


def test_a_memberless_shared_row_is_not_the_items(test_db):
    cases = _seed_old(test_db, run_qa=False)
    shared = _memberless_copy(test_db, cases[WAITING])
    [hold] = open_stage_holds(test_db, item_id=WAITING, stage=ITEM_QA_STAGE)
    assert shared not in hold.requirement_ids


def test_production_holding_the_rows_wins_over_a_stage_run_holding_none(test_db):
    """YOK-5401: both runs at item QA, only Production holds open rows."""
    cases = _seed_old(test_db, run_qa=False)
    held = _sibling_holding(test_db, PRODUCTION, PASSED, cases[PASSED])
    assert _select(test_db, PASSED) == PRODUCTION
    [hold] = open_stage_holds(test_db, item_id=PASSED, stage=ITEM_QA_STAGE)
    assert hold.requirement_ids == (held,)


def test_two_runs_holding_open_rows_are_refused_with_both_named(test_db):
    cases = _seed_old(test_db, run_qa=False)
    copy = _sibling_holding(test_db, PRODUCTION, WAITING, cases[WAITING])
    with pytest.raises(QaItemStageAmbiguous) as refused:
        _select(test_db, WAITING)
    message = str(refused.value)
    assert f"{OLD} (environment" in message and f"{PRODUCTION} (environment" in message
    assert f"requirements {cases[WAITING]}" in message
    assert f"requirements {copy}" in message
    assert "--deployment-run-id RUN" in message
    assert _select(test_db, WAITING, requested_run_id=PRODUCTION) == PRODUCTION


def test_named_run_must_hold_the_item(test_db):
    cases = _seed_old(test_db, run_qa=False)
    _sibling_holding(test_db, PRODUCTION, PASSED, cases[PASSED])
    assert _select(test_db, WAITING, requested_run_id=OLD) == OLD
    with pytest.raises(QaItemRunNotMember) as refused:
        _select(test_db, WAITING, requested_run_id=PRODUCTION)
    assert f"YOK-{WAITING} is not a member of run {PRODUCTION}" in str(refused.value)
    assert f"open 'item-qa' requirements are on {OLD}" in str(refused.value)
    with pytest.raises(QaItemRunNotMember, match="no deployment run"):
        _select(test_db, WAITING, requested_run_id="run-absent")


def test_a_created_takeover_successor_holding_the_rows_is_named(test_db, monkeypatch):
    _seed_old(test_db, run_qa=False)
    _seed_new(test_db)
    _contains(monkeypatch)
    _take_over(test_db)
    with pytest.raises(QaItemStageUnavailable) as refused:
        _select(test_db, WAITING)
    message = str(refused.value)
    assert f"held by live run {NEW}" in message
    assert "has not reached 'item-qa'" in message
    assert "Do not start a new deployment" in message
    assert "deployment-runs create" not in message


def test_a_takeover_successor_at_the_stage_resolves(test_db, monkeypatch):
    _seed_old(test_db, run_qa=False)
    _seed_new(test_db)
    _contains(monkeypatch)
    _take_over(test_db)
    test_db.execute(
        "UPDATE deployment_runs SET status='executing', current_stage=%s WHERE id=%s",
        (ITEM_QA_STAGE, NEW),
    )
    test_db.commit()
    assert _requirement(test_db, NEW, ITEM_QA_STAGE, WAITING)
    assert _select(test_db, WAITING) == NEW
