"""A member's close-out costs the same however large its run is.

The driver closes accepted members one at a time, so every statement a
member's close-out repeats per run requirement or per sibling multiplies
across the whole stage. These tests pin that one member's gating reads and
its whole close-out issue the same statements on a small run and on a run
with more shared requirements and more members.
"""

from __future__ import annotations

import pytest

from runtime.api.domain.test_deployment_delivery_close_out_notice import _project
from runtime.api.domain.test_deployment_qa_shared_plans import _attach
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import HOLDER_A
from runtime.api.domain.test_no_obligation_member_close_out import _ready_member
from runtime.api.domain.test_status_transition_preflight import (
    _isolate_status_effects,
)
from runtime.api.fixtures.statement_counter import CountingConnection
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

#: run id -> (shared requirement count, (measured member, *siblings))
RUNS = {
    "run-close-out-small": (1, (9911, 9912, 9913)),
    "run-close-out-large": (6, (9914, 9915, 9916, 9917, 9918)),
}


def _seed(conn, run_id: str) -> int:
    """A parked member sharing one plan; its siblings share every plan."""
    count, (measured, *siblings) = RUNS[run_id]
    plans = [_plan(conn, f"{run_id}-{index}") for index in range(count)]
    stages = _stages(plans[0])
    stages[1].pop("cases")
    _ready_member(conn, measured, f"{HOLDER_A}-{run_id}")
    _seed_run(
        conn,
        run_id=run_id,
        stages=stages,
        members=tuple(siblings),
        existing_members=(measured,),
    )
    conn.execute(
        "UPDATE items SET deployment_flow=%s WHERE id=%s", (f"flow-{run_id}", measured)
    )
    conn.execute(
        "UPDATE deployment_run_items SET delivery_intent='final' WHERE run_id=%s",
        (run_id,),
    )
    _attach(conn, measured, plans[0])
    for sibling in siblings:
        for plan_id in plans:
            _attach(conn, sibling, plan_id)
    for member in (measured, *siblings):
        materialize_deployment_qa_stage(
            conn,
            deployment_run_id=run_id,
            deployment_stage="item-qa",
            deployment_member_item_id=member,
        )
    conn.execute(
        "UPDATE qa_requirements SET waived_at=NOW(),waiver_rationale='accepted',"
        "waiver_source='owner' WHERE deployment_run_id=%s",
        (run_id,),
    )
    conn.commit()
    shared = conn.execute(
        "SELECT COUNT(*) FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_member_item_id IS NULL",
        (run_id,),
    ).fetchone()[0]
    assert shared == count
    return measured


def _satisfied(conn, run_id, member):
    from yoke_core.domain.no_obligation_member_close_out import (
        satisfied_delivery_member,
    )

    assert satisfied_delivery_member(conn, item_id=member, run_id=run_id)


def _acceptance(conn, run_id, member):
    from yoke_core.domain.deployment_qa_run_acceptance import (
        item_qa_acceptance_blockers,
    )

    assert item_qa_acceptance_blockers(conn, run_id=run_id, item_id=member) == []


def _close_out(conn, run_id, member):
    from yoke_core.domain.deployment_qa_member_acceptance_notice import (
        notify_item_qa_accepted,
    )

    assert notify_item_qa_accepted(conn, run_id=run_id, item_id=member) == "closed"


@pytest.mark.parametrize("read", [_satisfied, _acceptance, _close_out])
def test_member_close_out_statements_do_not_grow_with_the_run(
    test_db, monkeypatch, read
) -> None:
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    counts = {}
    for run_id in RUNS:
        member = _seed(test_db, run_id)
        counting = CountingConnection(test_db)
        read(counting, run_id, member)
        counts[run_id] = counting.count
    assert len(set(counts.values())) == 1, f"statements grew with the run: {counts}"
