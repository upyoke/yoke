"""A later-stage dispatch does work linear in the run's members.

Each member's active-stage check once re-read every prior-stage member, and
every call re-sent every settled member's result notice. The statement
count of the materializing, the settling and a repeated dispatch on a
40-member run is pinned against a 20-member run: linear work at most
doubles, quadratic work about quadruples. The materializing dispatch also
stays under a per-member statement ceiling.
"""

from __future__ import annotations

from runtime.api.domain.test_deployment_qa_result_notice import OPERATOR, _member
from runtime.api.domain.test_deployment_qa_stage_execution import _plan, _seed_run
from runtime.api.domain.test_deployment_qa_stage_ordering import _stages
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import _project
from runtime.api.fixtures.statement_counter import CountingConnection
from yoke_core.domain import deployment_qa_result_notice as result_notice
from yoke_core.domain.actor_permissions import ROLE_OPERATOR
from yoke_core.domain import deployment_run_carried_work_source as sources
from yoke_core.domain import standalone_item_merge
from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)

_NOTIFICATION = {"enabled": True, "recipients": {"actors": [OPERATOR]}}


def _dispatch(conn, stage, run_id):
    return materialize_and_gate_deployment_qa_stage(conn, stage, run_id=run_id)


def _discharge(conn, run_id, stage):
    """Materialize every member's cases for ``stage``, then waive them.

    Returns how many statements the materializing dispatch issued.
    """
    conn.execute(
        "UPDATE deployment_runs SET current_stage=%s WHERE id=%s",
        (stage["name"], run_id),
    )
    conn.commit()
    counting = CountingConnection(conn)
    assert _dispatch(counting, stage, run_id)[0] == -4
    conn.execute(
        "UPDATE qa_requirements SET waived_at=NOW(),waiver_rationale='accepted',"
        "waiver_source='owner' WHERE deployment_run_id=%s AND deployment_stage=%s",
        (run_id, stage["name"]),
    )
    conn.commit()
    return counting.count


def _seed(conn, run_id, members):
    """Members accepted at a prior item stage, discharged at the current one."""
    stages = _stages(_plan(conn, f"{run_id}-plan"))[:3]
    stages[2]["notification"] = _NOTIFICATION
    _seed_run(conn, run_id=run_id, stages=stages, members=members)
    _discharge(conn, run_id, stages[1])
    assert _dispatch(conn, stages[1], run_id)[0] == 0
    return stages[2], _discharge(conn, run_id, stages[2])


def _isolate_external_calls(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("dispatch reached git or GitHub")

    monkeypatch.setattr(sources, "carried_work_sources", refuse)
    monkeypatch.setattr(standalone_item_merge, "sync_item_to_github", refuse)


def test_later_stage_dispatch_statements_grow_linearly(test_db, monkeypatch):
    _isolate_external_calls(monkeypatch)
    _project(test_db)
    _member(test_db, OPERATOR, role=ROLE_OPERATOR)
    sent = []
    real_notify = result_notice.notify_qa_stage_result
    monkeypatch.setattr(
        result_notice,
        "notify_qa_stage_result",
        lambda conn, **kw: sent.append(kw["member_item_id"]) or real_notify(conn, **kw),
    )
    counts = {}
    for size, first in ((20, 9501), (40, 9601)):
        run_id = f"run-dispatch-scaling-{size}"
        members = tuple(range(first, first + size))
        stage, counts[size, "materialize"] = _seed(test_db, run_id, members)
        for call in ("settle", "repeat"):
            sent.clear()
            conn = CountingConnection(test_db)
            assert _dispatch(conn, stage, run_id)[0] == 0
            counts[size, call] = conn.count
            assert sent == (list(members) if call == "settle" else []), call
    for call in ("materialize", "settle", "repeat"):
        assert counts[40, call] <= 2 * counts[20, call], counts
    # The materializing dispatch writes its cohort under one run lock, so a
    # member costs its own reads and writes only, never a lock per member.
    assert counts[40, "materialize"] <= 20 * 40, counts
