"""Diagnostic copy safety, complete aggregate census and enforced disk limits."""

import json
import shutil
import sys

import pytest

from yoke_core.domain.migration_copy_instant_inspection import (
    CopyInspection,
    GIB,
    inspection_plan,
)
from yoke_core.domain.migration_fleet_preflight import RehearsalPlan
from yoke_core.domain.migration_fleet_preflight_transfer import run_transfer


def test_inspection_scans_restored_values_without_applying_history(
    test_db, tmp_path, monkeypatch
):
    from yoke_core.domain import db_helpers
    from yoke_core.tools import stored_instant_census

    monkeypatch.setattr(
        stored_instant_census,
        "STORED_INSTANT_COLUMNS",
        (("instant_census_fixture", "timestamp"),),
    )
    plan = RehearsalPlan(
        ("must_not_apply",),
        lambda *_: pytest.fail("history read"),
        lambda *_: pytest.fail("history applied"),
        post_converge_validator=lambda *_: pytest.fail("release-driver write"),
    )
    free = shutil.disk_usage(tmp_path).free // GIB
    assert free > 3
    diagnostic = inspection_plan(plan, tmp_path, 1, 1, "fixture", lambda _: None)
    assert (
        diagnostic.success_detail == "diagnostic census collected; no history applied"
    )
    dump = tmp_path / "fixture.dump"
    dump.write_bytes(b"private archive fixture")
    diagnostic.copy_observer("start", dump)
    with db_helpers.connect() as conn:
        conn.execute("CREATE TABLE instant_census_fixture (timestamp TEXT NOT NULL)")
        for value in (
            "2026-10-08T16:30:00.123456Z",
            "2026-10-08T12:30:00.123456-04:00",
            "",
            "2026-10-08 16:30:00",
            "2026-02-29T00:00:00Z",
            "2026-10-08T24:00:00Z",
            "2026-10-08T16:30:00-00:00",
            "2026-10-08 16:30:00.123456+00",
            "2026-10-08 12:30:00-0400",
            "2026-10-08T16:30:00.1234567+00:00",
            "2026-10-08",
            "not an instant",
        ):
            conn.execute("INSERT INTO instant_census_fixture VALUES (%s)", (value,))
        conn.commit()
        assert diagnostic.history == ()
        assert diagnostic.pending_names(conn, ()) == ()
        diagnostic.converge(conn, "never-log-this-dsn")
        assert conn.execute("SHOW transaction_read_only").fetchone()[0] == "on"
        assert diagnostic.post_converge_validator(conn, "never-log-this-dsn") is None
        assert (
            conn.execute("SELECT COUNT(*) FROM instant_census_fixture").fetchone()[0]
            == 12
        )
    report = json.loads((tmp_path / "fixture.instants.json").read_text())
    assert report["complete"]
    column = report["columns"][0]
    assert column["rows"] == 12
    assert column["blank"] == 1
    assert column["non_rfc3339"] == 7
    assert column["invalid_calendar_or_value"] == 2
    assert column["unknown_offset"] == 1
    assert column["format_shapes"] == {
        "qualified_calendar": 8,
        "calendar_without_offset": 1,
        "date_without_time": 1,
        "other_value": 1,
    }
    assert "never-log-this-dsn" not in (tmp_path / "fixture.resources.json").read_text()


def test_budget_refuses_before_copy_and_preserves_free_space(tmp_path, monkeypatch):
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda _: shutil._ntuple_diskusage(250 * GIB, 200 * GIB, 50 * GIB),
    )
    with pytest.raises(ValueError, match="copy_budget_unavailable"):
        CopyInspection(tmp_path, 80, 32, "fixture", lambda _: None)
    inspection = CopyInspection(tmp_path, 10, 32, "fixture", lambda _: None)
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda _: shutil._ntuple_diskusage(250 * GIB, 220 * GIB, 30 * GIB),
    )
    with pytest.raises(RuntimeError, match="copy_budget_exceeded"):
        inspection.guard()


def test_transfer_kills_its_child_when_resource_guard_refuses():
    def refuse():
        raise RuntimeError("copy_budget_exceeded")

    with pytest.raises(RuntimeError, match="copy_budget_exceeded"):
        run_transfer(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            timeout=90,
            resource_guard=refuse,
        )


def test_diagnostic_mode_cannot_record_a_release_receipt(tmp_path, capsys):
    from runtime.api.tools.preflight_fleet_migrations import main

    assert (
        main(
            [
                "--project",
                "fixture",
                "prod",
                "--instant-census-output",
                str(tmp_path),
                "--record-receipt",
            ]
        )
        == 2
    )
    assert "instant_census_diagnostic_only" in capsys.readouterr().err
