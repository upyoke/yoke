"""The report's deployment-run section costs the same statements at any size.

Its reads used to grow with what they read: one review-wait lookup per
unpassed requirement, seven gate reads per item-QA member, and a fresh set
of stage reads per live run. Each now answers for the whole set, so a
larger fleet changes the answer, not the number of statements behind it.
"""

from __future__ import annotations

from runtime.api.domain.test_steering_fleet_report_deployment_run_facts import (
    STAGE_RELEASE,
    _record_verdict,
    _seed_requirement,
    _seed_run,
)
from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)
from runtime.api.fixtures.statement_counter import CountingConnection
from runtime.api.steering_fleet_test_helpers import PROJECT_ID, seed_steering_scope
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.steering_fleet_report_run_progress import run_progress


def _seed_fleet(
    conn, *, first: int, runs: int, members: int, requirements: int
) -> None:
    """``runs`` item-QA runs and ``runs`` release runs carrying red and open QA."""
    for index in range(first, first + runs):
        qa_run = f"run-20260926-1{index:02d}"
        seed_run_standing_on_qa_stage(
            conn,
            run_id=qa_run,
            project="yoke",
            stages=item_qa_stage_definitions(None),
            members=tuple(7000 + 100 * index + k for k in range(members)),
            lineage="e" * 40,
        )
        release_seeded_driver(conn, qa_run)
        release_run = f"run-20260926-2{index:02d}"
        _seed_run(conn, run_id=release_run, stage=STAGE_RELEASE)
        for k in range(requirements):
            requirement_id = 80000 + 1000 * index + k
            _seed_requirement(
                conn,
                run_id=release_run,
                requirement_id=requirement_id,
                member_item_id=1,
            )
            if k % 2:
                _record_verdict(conn, requirement_id=requirement_id, verdict="fail")
    conn.commit()


def _statements(conn) -> tuple[int, int]:
    counting = CountingConnection(conn)
    rows = run_progress(
        counting, project_id=PROJECT_ID, now=parse_instant(iso8601_now())
    )
    return counting.count, len(rows)


def test_run_section_statements_do_not_grow_with_runs_members_or_requirements(
    test_db,
) -> None:
    small = seed_steering_scope(test_db)
    _seed_fleet(small, first=0, runs=1, members=2, requirements=2)
    small_count, small_rows = _statements(small)

    _seed_fleet(small, first=1, runs=3, members=8, requirements=12)
    large_count, large_rows = _statements(small)

    assert (small_rows, large_rows) == (2, 8)
    assert large_count == small_count, (
        f"run section statements grew from {small_count} to {large_count}"
    )


def test_a_large_fleet_still_reports_each_run_and_its_reds(test_db) -> None:
    conn = seed_steering_scope(test_db)
    _seed_fleet(conn, first=0, runs=2, members=3, requirements=4)

    rows = {
        row.run_id: row
        for row in run_progress(
            conn, project_id=PROJECT_ID, now=parse_instant(iso8601_now())
        )
    }

    release = rows["run-20260926-200"]
    assert [red.requirement_id for red in release.red] == [80001, 80003]
    assert release.total_blocking == 4
    qa = rows["run-20260926-100"]
    assert qa.total_blocking == 3
    assert len(qa.member_lines) == qa.outstanding
