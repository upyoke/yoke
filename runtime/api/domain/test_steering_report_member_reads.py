"""Deliver reports read unmaterialized member plans in batches without locks."""

from runtime.api.fixtures.backlog import insert_item
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
from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.db_helpers import utc_now
from yoke_core.domain.deployment_requirement_snapshots import (
    requirement_selection,
    snapshot_member_requirements,
)
from yoke_core.domain.steering_fleet_report_compose import (
    combined_dict,
    compose_held_reports,
)


RUN = "run-member-report"


def _add_member(conn, member):
    insert_item(conn, id=member, workflow_id="issue", status="done")
    plan = create_smoke_plan(conn, project="yoke", slug=f"member-smoke-{member}")
    conn.execute(
        "INSERT INTO qa_plan_item_attachments "
        "(item_id,plan_id,transition_id,qa_phase,attached_at) "
        "VALUES (%s,%s,'release','post_deploy',%s)",
        (member, plan, utc_now()),
    )
    conn.execute(
        "INSERT INTO deployment_run_items "
        "(run_id,item_id,added_at,requirement_snapshot) VALUES (%s,%s,%s,%s)",
        (
            RUN,
            member,
            utc_now(),
            snapshot_member_requirements(
                conn, run_id=RUN, item_id=member, selection_json=requirement_selection()
            ),
        ),
    )
    conn.commit()


def _seed(conn):
    seed_steering_scope(conn)
    seed_run_standing_on_qa_stage(
        conn,
        run_id=RUN,
        project="yoke",
        stages=item_qa_stage_definitions(None),
        members=(),
        lineage="e" * 40,
    )
    assert connection_is_postgres(conn)


def _report(conn, now):
    return compose_held_reports(
        conn, session_id=STEERING_SESSION, now=now, include_inventory=False
    )


def test_deliver_report_queries_do_not_scale_with_unmaterialized_members(test_db):
    _seed(test_db)
    now = format_instant(utc_now())
    counts = []
    seeded = 0
    for size in (1, 10, 30):
        for index in range(seeded, size):
            _add_member(test_db, 7000 + index)
        seeded = size
        counted = CountingConnection(test_db)
        report = _report(counted, now)
        [run] = report.sections[0].report.deployment_runs
        assert run.run_id == RUN
        assert run.outstanding == run.total_blocking == size
        assert len(run.member_lines) == size
        assert all(
            f"member YOK-{7000 + index}:" in run.member_lines[index]
            for index in range(size)
        )
        assert (
            test_db.execute(
                "SELECT count(*) FROM qa_requirements WHERE deployment_run_id=%s "
                "AND method_id IS NOT NULL",
                (RUN,),
            ).fetchone()[0]
            == 0
        )
        locks = [
            sql
            for sql in counted.statements
            if "LOCK TABLE" in sql.upper() or "FOR UPDATE" in sql.upper()
        ]
        assert locks == [], f"report took write locks: {locks}"
        plan_reads = [sql for sql in counted.statements if "FROM qa_plans WHERE" in sql]
        assert len(plan_reads) == 1 and "id IN (" in plan_reads[0]
        assert counted.statements[plan_reads[0]] == 1
        counts.append(counted.count)
    assert counts[0] == counts[1] == counts[2], counts


def test_unlocked_member_plan_reads_preserve_report_content(test_db, monkeypatch):
    from yoke_core.domain import deployment_qa_stage_outstanding as outstanding

    _seed(test_db)
    for member in (7000, 7001):
        _add_member(test_db, member)
    now = format_instant(utc_now())
    unlocked = _report(test_db, now)
    original = outstanding.frozen_stage_plans

    def locked(conn, subject, **kwargs):
        return original(conn, subject, **{**kwargs, "lock_plans": True})

    monkeypatch.setattr(outstanding, "frozen_stage_plans", locked)
    assert combined_dict(unlocked) == combined_dict(_report(test_db, now))
