"""A member's close-out costs the same however large its run is.

The driver closes accepted members one at a time, so every statement a
member's close-out repeats per run requirement or per sibling multiplies
across the whole stage. These tests pin that one member's gating reads and
its whole close-out issue the same statements on a small run and on a run
with more shared requirements and more members.
"""

from __future__ import annotations

from runtime.api.domain.member_close_out_round_trips_test_support import (
    RUNS as RUNS,
    _pass_group as _pass_group,
    _seed as _seed,
)


import pytest

from runtime.api.domain.deployment_delivery_close_out_notice_test_support import (
    _project,
)
from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)
from runtime.api.fixtures.statement_counter import CountingConnection

#: run id -> (plan group count, (measured member, *siblings))


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
