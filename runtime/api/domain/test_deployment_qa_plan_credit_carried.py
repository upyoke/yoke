"""Pending successor acceptance distinguishes recorded passes from owed cases."""

import pytest

from runtime.api.domain.deployment_qa_plan_groups_test_support import _attach
from runtime.api.domain.deployment_run_target_takeover_test_support import (
    NEW,
    OLD,
    PASSED,
    WAITING,
    _contains,
    _seed_new,
    _seed_old,
    _take_over,
)
from runtime.api.domain.test_deployment_qa_moved_member_hold import _freeze_successor
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import record_case_verdict
from yoke_core.domain import deployment_item_completion_runs as completion
from yoke_core.domain.deployment_qa_plan_credit import (
    plan_credit_misses,
    plan_credit_wait_reason,
)
from yoke_core.domain.qa_done_gate_refusal import done_gate_refusal_errors
from yoke_core.domain.qa_gate_summary_rows import plan_group_miss_rows


def _move_member(conn, monkeypatch, member):
    cases = _seed_old(conn, run_qa=False)
    requirement = cases[member]
    plan = conn.execute(
        "SELECT plan_id FROM qa_requirements WHERE id=%s", (requirement,)
    ).fetchone()[0]
    _attach(conn, member, plan)
    _seed_new(conn)
    _contains(monkeypatch)
    assert _take_over(conn) == OLD

    def successor(conn, **_):
        stage = conn.execute(
            "SELECT current_stage FROM deployment_runs WHERE id=%s", (NEW,)
        ).fetchone()[0]
        return {"id": NEW, "current_stage": stage}

    monkeypatch.setattr(completion, "latest_qa_member_run", successor)
    return requirement


@pytest.mark.parametrize("ready", [False, True], ids=["before-item-qa", "at-item-qa"])
def test_recorded_pass_waits_for_successor_credit(test_db, monkeypatch, ready):
    member = WAITING if ready else PASSED
    requirement = _move_member(test_db, monkeypatch, member)
    if ready:
        # The moved walk can first record its pass after the transfer.
        record_case_verdict(test_db, requirement, "pass", evidence=True)
        _freeze_successor(test_db)

    [miss] = plan_credit_misses(test_db, member)

    assert miss["carried"] is True
    assert f"requirement #{requirement} carries when {NEW} reaches item-qa" in miss["recovery"]
    expected = (
        f"Awaiting {NEW} reaching item-qa to credit the carried pass "
        f"for plan {miss['plan_slug']}; do not re-run."
    )
    assert plan_credit_wait_reason(miss) == expected
    [summary_miss] = plan_group_miss_rows(test_db, member)
    assert summary_miss["carried"] is True
    assert summary_miss["wait_reason"] == expected
    refusal = "\n".join(done_gate_refusal_errors(test_db, [miss], name="the member"))
    assert expected in refusal
    assert "Next: Do not re-run." in refusal
    assert "yoke qa plan run" not in refusal


def test_retargeted_destination_still_owes_the_plan(test_db, monkeypatch):
    _move_member(test_db, monkeypatch, PASSED)
    new_url = "https://new-destination.example.test"
    test_db.execute(
        "UPDATE environments SET url=%s WHERE name='stage' AND project_id="
        "(SELECT project_id FROM deployment_runs WHERE id=%s)",
        (new_url, NEW),
    )
    _freeze_successor(test_db, url=new_url)

    [miss] = plan_credit_misses(test_db, PASSED)

    assert miss["carried"] is False
    assert "yoke qa plan run --item" in miss["recovery"]
    assert "carried pass" not in plan_credit_wait_reason(miss)
