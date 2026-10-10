"""Onboarding and projected QA methods keep native clocks at their owners."""

import json
from datetime import datetime, timedelta

import pytest
from yoke_contracts.timestamps import InvalidInstant, parse_instant, temporal_wire
from yoke_core.domain import project_onboarding_runs as runs
from yoke_core.domain import project_onboarding_run_supersede as reconciliation
from yoke_core.domain import machine_qa_pack as pack
from runtime.api.domain.test_project_onboarding_runs import _conn

STAMP = parse_instant("1969-12-31T05:44:59.123456+05:45")
ZONES = ["UTC", "America/New_York", "Asia/Kathmandu"]
OPAQUE = {"calendar": "1970-01-01", "provider_clock": "unqualified evidence"}


@pytest.mark.parametrize("zone", ZONES)
def test_checklist_update_shares_native_fact_without_interpreting_evidence(
    monkeypatch, zone
):
    conn = _conn()
    try:
        conn.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
        clock = [STAMP]
        monkeypatch.setattr(runs, "utc_now", lambda: clock[0])
        first = runs.init_run(conn=conn, run_id="clock-run", metadata=OPAQUE)
        assert first["created_at"] == STAMP
        assert first["updated_at"] == STAMP
        assert first["metadata"]["provider_clock"] == OPAQUE["provider_clock"]
        clock[0] += timedelta(microseconds=1)
        second = runs.update_run(
            conn=conn,
            run_id="clock-run",
            row_status={"machine-profile": "verified"},
            evidence={"machine-profile": OPAQUE},
            blocker={"machine-profile": None},
            note={"machine-profile": "Clock evidence"},
        )
        assert second["created_at"] == STAMP
        assert second["updated_at"] == clock[0]
        assert temporal_wire(second)["updated_at"] == "1969-12-30T23:59:59.123457Z"
        row = conn.execute(
            "SELECT created_at,updated_at FROM project_onboarding_runs WHERE run_id='clock-run'"
        ).fetchone()
        assert row == (STAMP, clock[0])
        assert all(
            row[0] == clock[0]
            for row in conn.execute(
                "SELECT updated_at FROM project_onboarding_checklist_rows WHERE run_id='clock-run'"
            ).fetchall()
        )
        profile = next(
            row for row in second["rows"] if row["row_id"] == "machine-profile"
        )
        assert profile["evidence"] == OPAQUE
    finally:
        conn.close()


@pytest.mark.parametrize("zone", ZONES)
def test_overtaking_deployment_compares_exact_instants_and_formats_only_new_metadata(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    monkeypatch.setattr(runs, "utc_now", lambda: STAMP)
    runs.init_run(conn=test_db, run_id="clock-run", project_id=1, metadata=OPAQUE)
    test_db.execute(
        "INSERT INTO deployment_runs (id,project_id,flow,status,created_at,completed_at) VALUES ('clock-deployment',1,'clock-flow','failed',%s,%s)",
        (STAMP, STAMP),
    )
    test_db.commit()
    assert reconciliation.supersede_overtaken_runs(test_db) == []
    later = STAMP + timedelta(microseconds=1)
    test_db.execute(
        "UPDATE deployment_runs SET completed_at=%s WHERE id='clock-deployment'",
        (later,),
    )
    test_db.commit()
    reconciled_at = later + timedelta(microseconds=1)
    monkeypatch.setattr(reconciliation, "utc_now", lambda: reconciled_at)
    [result] = reconciliation.supersede_overtaken_runs(test_db)
    assert result["at"] == later
    row = test_db.execute(
        "SELECT status,updated_at,metadata_json FROM project_onboarding_runs WHERE run_id='clock-run'"
    ).fetchone()
    assert row[:2] == ("superseded", reconciled_at)
    document = json.loads(row[2])
    assert document["provider_clock"] == OPAQUE["provider_clock"]
    clocks = document[reconciliation.SUPERSEDED_BY_KEY]
    assert clocks["at"] == "1969-12-30T23:59:59.123457Z"
    assert clocks["reconciled_at"] == "1969-12-30T23:59:59.123458Z"
    decoded = reconciliation.superseded_by(row[2])
    assert decoded["at"] == later
    assert decoded["reconciled_at"] == reconciled_at
    assert reconciliation.supersede_overtaken_runs(test_db) == []


@pytest.mark.parametrize("zone", ZONES)
def test_pack_projection_binds_native_method_creation_and_update(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    version, definitions = pack.load_machine_qa_methods()
    method = {**definitions[0], "id": "clock-qa-method"}
    monkeypatch.setattr(pack, "load_machine_qa_methods", lambda: (version, [method]))
    clock = [STAMP]
    monkeypatch.setattr(pack, "utc_now", lambda: clock[0])
    assert pack.sync_machine_qa_pack_methods(test_db) == [method]
    assert test_db.execute(
        "SELECT created_at,updated_at FROM qa_methods WHERE id=%s", (method["id"],)
    ).fetchone() == (STAMP, STAMP)
    clock[0] += timedelta(microseconds=1)
    pack.sync_machine_qa_pack_methods(test_db)
    assert test_db.execute(
        "SELECT created_at,updated_at FROM qa_methods WHERE id=%s", (method["id"],)
    ).fetchone() == (STAMP, clock[0])


@pytest.mark.parametrize(
    "bad", [None, "", "1970-01-01", "1970-01-01T00:00:00", 0, datetime(1970, 1, 1)]
)
def test_bad_onboarding_comparison_clock_refuses_before_database_access(bad):
    with pytest.raises(InvalidInstant):
        reconciliation._overtaking_deployment(object(), 1, bad)
