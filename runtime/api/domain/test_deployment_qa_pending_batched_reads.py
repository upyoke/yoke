"""The driver's QA-pending read costs the same statements at any run size.

The production driver runs on an operator's laptop and reaches the control
plane over a slow link, so every statement costs a round trip. The read once
asked pass currency and review waits once per requirement row, so a 44-member
run outlived its read deadline. Each fact is now read once for the whole set,
inside one composition scope, so a larger run changes the answer and not the
number of statements behind it.
"""

from __future__ import annotations

from runtime.api.domain.test_steering_fleet_report_deployment_run_facts import (
    _record_verdict,
    _seed_requirement,
)
from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)
from runtime.api.fixtures.statement_counter import CountingConnection
from runtime.api.steering_fleet_test_helpers import seed_steering_scope
from yoke_core.domain.handlers.deployment_run_execution_qa import _qa_pending


def _seed(conn, *, run_id: str, first_member: int, members: int) -> list[int]:
    """A run on its item-QA stage whose odd members' blocking QA failed."""
    member_ids = tuple(first_member + k for k in range(members))
    seed_run_standing_on_qa_stage(
        conn,
        run_id=run_id,
        project="yoke",
        stages=item_qa_stage_definitions(None),
        members=member_ids,
        lineage="e" * 40,
    )
    release_seeded_driver(conn, run_id)
    failed = []
    for k, member in enumerate(member_ids):
        requirement_id = 10 * member
        _seed_requirement(
            conn, run_id=run_id, requirement_id=requirement_id, member_item_id=member
        )
        verdict = "fail" if k % 2 else "pass"
        _record_verdict(conn, requirement_id=requirement_id, verdict=verdict)
        if verdict == "fail":
            failed.append(requirement_id)
    conn.commit()
    return failed


def _read(conn, run_id: str) -> tuple[int, dict]:
    counting = CountingConnection(conn)
    result = _qa_pending(counting, run_id, ITEM_QA_STAGE)
    return counting.count, result


def test_qa_pending_statements_do_not_grow_with_members(test_db) -> None:
    conn = seed_steering_scope(test_db)
    _seed(conn, run_id="run-20261016-001", first_member=7100, members=4)
    small_count, small = _read(conn, "run-20261016-001")

    _seed(conn, run_id="run-20261016-002", first_member=7200, members=44)
    large_count, large = _read(conn, "run-20261016-002")

    assert (len(small["unresolved"]), len(large["unresolved"])) == (2, 22)
    assert large_count == small_count, (
        f"qa_pending statements grew from {small_count} to {large_count}"
    )


def test_only_requirements_without_a_current_pass_are_reported(test_db) -> None:
    conn = seed_steering_scope(test_db)
    failed = _seed(conn, run_id="run-20261016-003", first_member=7300, members=4)

    _, result = _read(conn, "run-20261016-003")

    assert result["unresolved"] == [
        f"requirement #{requirement_id} (browser): no passing run"
        for requirement_id in failed
    ]
    assert result["held_report"][0].startswith("final stage held")
