"""Landed rows read each item's done gate without scaling by release history.

A long-lived item collects a deployment membership for every release
takeover. The report's landed section reads every landed item's done gate,
so a per-membership read there multiplied report cost by history length.
"""

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    create_smoke_plan,
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)
from runtime.api.fixtures.statement_counter import CountingConnection
from runtime.api.steering_fleet_test_helpers import (
    STEERING_SESSION,
    seed_steering_scope,
)
from yoke_contracts.timestamps import format_instant
from yoke_core.domain.db_helpers import utc_now
from yoke_core.domain.deployment_item_completion_runs import completion_runs
from yoke_core.domain.deployment_run_member_targeting import supplemental_qa_run
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.steering_fleet_report_compose import (
    combined_dict,
    compose_held_reports,
)


RUN = "run-landed-history"
MEMBERS = tuple(range(7500, 7505))


def _seed(conn):
    seed_steering_scope(conn)
    plan = create_smoke_plan(conn, project="yoke", slug="landed-history-smoke")
    seed_run_standing_on_qa_stage(
        conn, run_id=RUN, project="yoke",
        stages=item_qa_stage_definitions(plan), members=MEMBERS, lineage="e" * 40,
    )
    conn.execute(
        "UPDATE items SET status='release',merged_at=%s,deployment_flow=%s "
        "WHERE id=ANY(%s)",
        (utc_now(), f"flow-{RUN}", list(MEMBERS)),
    )
    conn.commit()


def _add_history(conn, start, stop):
    """Older cancelled takeovers of the same flow carrying every member."""
    project_id = resolve_project_id(conn, "yoke")
    for index in range(start, stop):
        run_id = f"{RUN}-old-{index:03d}"
        created = f"2026-01-01T00:{index // 60:02d}:{index % 60:02d}+00:00"
        conn.execute(
            "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,"
            "status,current_stage,created_at) "
            "VALUES (%s,%s,%s,%s,'cancelled','item-qa',%s)",
            (run_id, project_id, f"flow-{RUN}", "d" * 40, created),
        )
        for member in MEMBERS:
            conn.execute(
                "INSERT INTO deployment_run_items(run_id,item_id,added_at) "
                "VALUES (%s,%s,%s)",
                (run_id, member, created),
            )
    conn.commit()


def _report(conn, now):
    return compose_held_reports(
        conn, session_id=STEERING_SESSION, now=now, include_inventory=False
    )


def test_landed_gate_reads_do_not_scale_with_release_history(test_db):
    _seed(test_db)
    now = format_instant(utc_now())
    counts, gates, bodies = [], [], []
    seeded = 0
    for history in (0, 10, 30):
        _add_history(test_db, seeded, history)
        seeded = history
        counted = CountingConnection(test_db)
        report = _report(counted, now)
        landed = report.sections[0].report.landed_open
        assert {row.item_id for row in landed} == set(MEMBERS)
        assert (
            len(completion_runs(test_db, MEMBERS[0], include_qa=True))
            == history + 1
        )
        counts.append(counted.count)
        gates.append(tuple((row.item_id, row.delivery_gate) for row in landed))
        bodies.append(combined_dict(report))
    assert counts[0] == counts[1] == counts[2], counts
    # Older cancelled attempts never shadow the live run: identical answers.
    assert gates[0] == gates[1] == gates[2]
    assert bodies[0] == bodies[1] == bodies[2]


def test_batched_supplemental_filter_matches_per_run_answer(test_db):
    _seed(test_db)
    _add_history(test_db, 0, 3)
    project_id = resolve_project_id(test_db, "yoke")
    test_db.execute(
        "INSERT INTO environments(site,project_id,name,url,settings,created_at) "
        "SELECT site,project_id,'prod','https://prod.example.test','{}',created_at "
        "FROM environments WHERE project_id=%s AND name='stage'",
        (project_id,),
    )
    # The completion flow now targets prod; the stage-target runs become
    # supplemental QA runs and leave the completion walk.
    test_db.execute(
        "UPDATE deployment_flows SET target_tier='persistent',target_environment_id="
        "(SELECT id FROM environments WHERE project_id=%s AND name='prod') "
        "WHERE id=%s",
        (project_id, f"flow-{RUN}"),
    )
    test_db.execute(
        "UPDATE deployment_runs SET target_tier='persistent',target_environment_id="
        "(SELECT id FROM environments WHERE project_id=%s AND name='stage') "
        "WHERE id IN (%s,%s)",
        (project_id, RUN, f"{RUN}-old-001"),
    )
    test_db.commit()
    member = MEMBERS[0]
    every = completion_runs(test_db, member, include_qa=True)
    expected = [
        run["id"] for run in every
        if not supplemental_qa_run(test_db, run_id=run["id"], item_id=member)
    ]
    assert len(expected) == 2
    assert [run["id"] for run in completion_runs(test_db, member)] == expected
