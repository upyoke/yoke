"""Native landing cadence and receipt projections preserve microsecond facts."""

import hashlib
import json
from datetime import timedelta

import pytest

from yoke_contracts.timestamps import format_instant, parse_instant, temporal_wire
from yoke_core.domain import last_doctor_run_read, merge_queue_landing_refresh
from yoke_core.domain.yoke_function_dispatch_events import serialize_payload

STAMP = parse_instant("1970-01-01T05:29:59.123456+05:30")


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_refresh_cadence_keeps_exact_native_boundary(test_db, zone):
    from yoke_core.domain.merge_queue_landing_record_schema import (
        ensure_merge_queue_landing_record_schema,
    )

    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    ensure_merge_queue_landing_record_schema(test_db)
    floor = STAMP - timedelta(seconds=60)
    assert merge_queue_landing_refresh.claim_due_projects(
        test_db, [1], now=floor, cadence_seconds=60
    ) == (1,)
    assert (
        merge_queue_landing_refresh.claim_due_projects(
            test_db, [1], now=STAMP - timedelta(microseconds=1), cadence_seconds=60
        )
        == ()
    )
    assert merge_queue_landing_refresh.claim_due_projects(
        test_db, [1], now=STAMP, cadence_seconds=60
    ) == (1,)
    merge_queue_landing_refresh.complete_projects(test_db, [1], now=STAMP)
    fact = merge_queue_landing_refresh.read_refresh(test_db, 1)
    assert fact.started_at == fact.completed_at == STAMP
    assert fact.payload()["started_at"] == "1969-12-31T23:59:59.123456Z"
    assert (
        merge_queue_landing_refresh.read_refresh(test_db, 2).payload()["started_at"]
        is None
    )


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_doctor_receipt_native_storage_and_wire_projection(test_db, zone):
    from yoke_core.domain.health_runs_schema import ensure_doctor_runs_schema

    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    ensure_doctor_runs_schema(test_db)
    last_doctor_run_read.record_doctor_run(
        test_db, {"ran_at": STAMP, "project": "yoke", "results": []}
    )
    row = test_db.execute(
        "SELECT ran_at, project, scope, runtime, fail_count, pass_count, "
        "warn_count, na_count, results FROM doctor_runs"
    ).fetchone()
    assert row[0] == STAMP
    assert last_doctor_run_read._serve_row(row)["ran_at"] == format_instant(STAMP)


def test_new_payload_digest_projects_native_clocks_and_preserves_opaque_values():
    native = {
        "clock": STAMP,
        "unknown": None,
        "token": "1970-01-01T00:00:00Z",
        "id": 2**53 + 1,
    }
    wire = temporal_wire(native)
    expected = json.dumps(wire, sort_keys=True, separators=(",", ":")).encode()
    assert serialize_payload(native) == (
        len(expected),
        hashlib.sha256(expected).hexdigest(),
    )
    assert wire["token"] == native["token"]
    assert native["clock"] == STAMP


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_merge_lock_keeps_native_expiry_and_exact_cutoff(test_db, monkeypatch, zone):
    from yoke_core.domain import merge_lock

    monkeypatch.setattr(merge_lock, "utc_now", lambda: STAMP)
    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    handle = merge_lock.acquire("native-clock", conn=test_db, ttl_minutes=1)
    clocks = test_db.execute(
        "SELECT acquired_at, expires_at FROM merge_locks WHERE session_id=%s",
        (handle.session_id,),
    ).fetchone()
    assert tuple(clocks) == (STAMP, STAMP + timedelta(minutes=1))
    assert merge_lock._rows_over_connection(test_db, STAMP + timedelta(minutes=1))
    assert not merge_lock._rows_over_connection(
        test_db, STAMP + timedelta(minutes=1, microseconds=1)
    )


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_ephemeral_cleanup_preserves_exact_cutoff_and_native_stopped_fact(
    test_db, monkeypatch, zone
):
    from yoke_core.domain import ephemeral_env

    monkeypatch.setattr(ephemeral_env, "utc_now", lambda: STAMP)
    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    floor = STAMP - timedelta(hours=24)
    for branch, clock in (
        ("before", floor - timedelta(microseconds=1)),
        ("exact", floor),
    ):
        test_db.execute(
            "INSERT INTO ephemeral_environments (project_id, branch, status, created_at) "
            "VALUES (%s, %s, 'running', %s)",
            (1, branch, clock),
        )
    test_db.commit()
    ephemeral_env.cmd_cleanup(test_db, max_age_hours=24)
    facts = test_db.execute(
        "SELECT branch, status, stopped_at FROM ephemeral_environments ORDER BY branch"
    ).fetchall()
    assert tuple(facts[0]) == ("before", "stopped", STAMP)
    assert tuple(facts[1]) == ("exact", "running", None)


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_qa_requirement_creation_and_waiver_bind_native_instants(
    test_db, monkeypatch, zone
):
    from runtime.api.fixtures.backlog_inserts import insert_item
    from yoke_core.domain.handlers.qa_requirement_insert import (
        RequirementSubject,
        execute_insert,
    )
    from yoke_core.domain import qa_requirement_ops
    from yoke_core.domain.qa_cli_requirement_insert import INSERT_SQL, insert_params

    class BindingRecorder:
        def __init__(self, conn):
            self._conn = conn
            self.bindings = []

        def execute(self, sql, params=()):
            if sql.startswith("INSERT INTO qa_requirements"):
                self.bindings.append(params[-1])
            return self._conn.execute(sql, params)

        def __getattr__(self, name):
            return getattr(self._conn, name)

    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    insert_item(test_db, id=1, title="Native QA clocks", status="implementing")
    conn = BindingRecorder(test_db)
    row = {"qa_kind": "ac_verification", "qa_phase": "verification"}
    requirement_id = execute_insert(
        conn, RequirementSubject.for_item(1), row, STAMP
    ).fetchone()[0]
    params = insert_params(
        conn=conn,
        item_id=1,
        epic_id=None,
        task_num=None,
        deployment_run_id=None,
        row=row,
        created_at=STAMP,
    )
    cli_id = test_db.execute(INSERT_SQL, params).fetchone()[0]
    assert conn.bindings == [STAMP]
    assert params[-1] == STAMP
    clocks = test_db.execute(
        "SELECT created_at FROM qa_requirements WHERE id IN (%s,%s) ORDER BY id",
        (requirement_id, cli_id),
    ).fetchall()
    assert [fact[0] for fact in clocks] == [STAMP, STAMP]
    monkeypatch.setattr(
        qa_requirement_ops, "utc_now", lambda: STAMP + timedelta(microseconds=1)
    )
    qa_requirement_ops.waive_requirement(
        test_db,
        req_id=requirement_id,
        rationale="Explicit waiver",
        source="human",
        force=True,
    )
    assert test_db.execute(
        "SELECT waived_at FROM qa_requirements WHERE id=%s", (requirement_id,)
    ).fetchone()[0] == STAMP + timedelta(microseconds=1)
