"""Report read costs at a sixty-session fleet size."""

import json

import pytest

from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.statement_counter import CountingConnection
from runtime.api.steering_fleet_test_helpers import (
    JUST_NOW,
    LONG_AGO,
    NOW,
    STEERING_SESSION,
    seed_session,
    seed_steering_scope,
)
from yoke_core.domain import steering_fleet_report_stranded as stranded
from yoke_core.domain.session_wake_meter import meter_wall
from yoke_core.domain.steering_fleet_report_compose import (
    combined_dict,
    compose_held_reports,
)
from runtime.api.domain.test_steering_fleet_report_stranded import (
    _exhausted_other_models,
    _pin_worker,
)


def _seed_workers(conn, start, stop):
    for index in range(start, stop):
        session = f"fleet-worker-{index}"
        seed_session(conn, session, last_tool_call_at=JUST_NOW)
        insert_item(
            conn,
            id=100 + index,
            title=f"Held work {index}",
            status="implementing",
            created_at=LONG_AGO,
            updated_at=LONG_AGO,
            spec="A complete work specification.",
        )
        conn.execute(
            "INSERT INTO work_claims "
            "(session_id, target_kind, scope, claimed_at, last_heartbeat) "
            "VALUES (%s, 'item', %s, %s, %s)",
            (session, json.dumps({"item_id": 100 + index}), JUST_NOW, JUST_NOW),
        )
    conn.commit()


def test_report_statement_count_does_not_grow_per_session(test_db):
    conn = seed_steering_scope(test_db)
    counts = []
    for start, stop in ((0, 1), (1, 10), (10, 60)):
        _seed_workers(conn, start, stop)
        counting = CountingConnection(conn)
        report = compose_held_reports(counting, session_id=STEERING_SESSION, now=NOW)
        assert len(report.sections) == 1
        counts.append(counting.count)
    assert counts[0] == counts[1] == counts[2]


@pytest.mark.parametrize("exhausted", [False, True])
def test_reusing_session_rows_preserves_entire_report(test_db, monkeypatch, exhausted):
    conn = seed_steering_scope(test_db)
    _seed_workers(conn, 0, 60)
    if exhausted:
        _pin_worker(conn, windows=_exhausted_other_models())
    reused = compose_held_reports(conn, session_id=STEERING_SESSION, now=NOW)
    assert bool(reused.sections[0].report.stranded) is exhausted

    def read_again(conn, row, now, *, limits):
        return meter_wall(conn, row["session_id"], now, limits=limits)

    monkeypatch.setattr(stranded, "meter_wall_for_session", read_again)
    reread = compose_held_reports(conn, session_id=STEERING_SESSION, now=NOW)
    assert combined_dict(reused) == combined_dict(reread)


def test_multi_project_report_queries_do_not_grow_with_relay_history(test_db):
    from runtime.api.domain.steering_claim_test_support import seed_project
    from yoke_core.domain.steering_claims import acquire
    from yoke_core.domain.session_surface_policy import clear_mark, set_mark

    conn = seed_steering_scope(test_db)
    _seed_workers(conn, 0, 6)
    for project in (71, 72):
        seed_project(conn, project, f"project-{project}")
        acquire(conn, session_id=STEERING_SESSION, project_id=project,
                reason="steering report")
    conn.execute("UPDATE session_relays SET project_checkouts=%s",
                 (json.dumps([1, 71, 72]),))
    conn.commit()
    counts = []
    for start, stop in ((0, 1), (1, 60)):
        for index in range(start, stop):
            conn.execute(
                "INSERT INTO session_relays "
                "(relay_id, actor_id, machine_id, hostname, surface_versions, "
                "project_checkouts, first_seen_at, last_seen_at, connected_until, state) "
                "VALUES (%s, 1, %s, 'expired', '{}', '[]', %s, %s, %s, 'idle')",
                (f"old-relay-{index}", f"old-machine-{index}",
                 LONG_AGO, LONG_AGO, LONG_AGO),
            )
        conn.commit()
        counted = CountingConnection(conn)
        report = compose_held_reports(counted, session_id=STEERING_SESSION, now=NOW)
        assert len(report.sections) == 3
        assert all(any(row.surface == "codex-cli" for row in s.report.launchable)
                   for s in report.sections)
        counts.append(counted.count)
        policy_reads = sum(n for sql, n in counted.statements.items()
                           if "FROM session_surface_policies" in sql)
        assert policy_reads == 3
    assert counts[0] == counts[1]
    assert counts[1] < 400

    mark = set_mark(conn, machine_id="machine-1", surface="codex-cli",
                    reason="operator hold", actor_id=1, session_id=STEERING_SESSION,
                    now=NOW)
    conn.commit()
    disabled = compose_held_reports(conn, session_id=STEERING_SESSION, now=NOW)
    assert all(not s.report.launchable for s in disabled.sections)
    clear_mark(conn, machine_id=mark["machine_id"], surface=mark["surface"],
               actor_id=1, now=NOW)
    conn.commit()
    restored = compose_held_reports(conn, session_id=STEERING_SESSION, now=NOW)
    assert combined_dict(restored) == combined_dict(report)
