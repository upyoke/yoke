"""Governed audit SQL facts stay native; new verification documents own wire clocks."""

import json
import subprocess
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain import migration_apply_audit as audit
from yoke_core.domain import migration_apply_contract as contract
from yoke_core.domain import migration_apply_verify as verify
from yoke_core.domain import migration_harness_checks as checks
from yoke_core.domain.migration_apply_format import format_rehearse
from yoke_core.domain.migration_audit_schema import ensure_migration_audit_table

MOMENT = parse_instant("2026-10-09T15:56:12.345678+05:45")
WIRE = "2026-10-09T10:11:12.345678Z"
OPAQUE = "2026-10-09 10:11:12+00:00"
ZONES = ["UTC", "America/New_York", "Asia/Kathmandu"]
WRITERS = [
    (audit._insert_audit_row, audit._update_audit_state),
    (checks.pg_insert_migration_audit_row, checks.pg_update_migration_audit_state),
]


def _insert(conn, insert):
    ensure_migration_audit_table(conn)
    return insert(
        conn,
        name="Native audit clock",
        model_name="clock-proof",
        project_id=1,
        session_id=None,
        test_copy_path=None,
        tables=[],
    )


@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize("insert,update", WRITERS)
def test_governed_audit_writers_preserve_native_clocks_null_and_opaque_fields(
    test_db, monkeypatch, zone, insert, update
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    monkeypatch.setattr(contract.db_helpers, "utc_now", lambda: MOMENT)
    audit_id = _insert(test_db, insert)
    later = MOMENT + timedelta(microseconds=1)
    update(
        test_db,
        audit_id,
        contract.STATE_REHEARSED,
        extra={
            "rehearsed_at": later,
            "completed_at": None,
            "source_fingerprint": OPAQUE,
        },
    )
    row = test_db.execute(
        "SELECT started_at,rehearsed_at,completed_at,source_fingerprint FROM migration_audit WHERE id=%s",
        (audit_id,),
    ).fetchone()
    assert tuple(row) == (MOMENT, later, None, OPAQUE)
    assert isinstance(row[0], datetime)


@pytest.mark.parametrize("insert,update", WRITERS)
@pytest.mark.parametrize(
    "value",
    [
        "",
        "2026-10-09",
        "2026-02-30T10:11:12Z",
        "2026-10-09T10:11:12",
        MOMENT.replace(tzinfo=None),
    ],
)
def test_invalid_update_clock_refuses_before_state_mutation(
    test_db, monkeypatch, insert, update, value
):
    monkeypatch.setattr(contract.db_helpers, "utc_now", lambda: MOMENT)
    audit_id = _insert(test_db, insert)
    with pytest.raises(ValueError):
        update(
            test_db, audit_id, contract.STATE_REHEARSED, extra={"rehearsed_at": value}
        )
    row = test_db.execute(
        "SELECT state,rehearsed_at FROM migration_audit WHERE id=%s", (audit_id,)
    ).fetchone()
    assert tuple(row) == (contract.STATE_PLANNED, None)


@pytest.mark.parametrize("insert,_update", WRITERS)
def test_naive_internal_audit_generator_refuses_before_insert(
    test_db, monkeypatch, insert, _update
):
    ensure_migration_audit_table(test_db)
    monkeypatch.setattr(
        contract.db_helpers, "utc_now", lambda: MOMENT.replace(tzinfo=None)
    )
    with pytest.raises(ValueError):
        _insert(test_db, insert)
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM migration_audit WHERE migration_name='Native audit clock'"
        ).fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("timeout", [False, True])
def test_new_verification_documents_format_clock_and_preserve_command_output(
    tmp_path, monkeypatch, timeout
):
    monkeypatch.setattr(verify, "_now", lambda: MOMENT)
    monkeypatch.setattr(verify, "_rehearsal_command_timeout_seconds", lambda: 1)

    def run(*_args, **_kwargs):
        if timeout:
            raise subprocess.TimeoutExpired("Verify clock", 1)
        return SimpleNamespace(returncode=0, stdout=OPAQUE, stderr="")

    monkeypatch.setattr(verify.subprocess, "run", run)
    outcomes, error = verify.run_rehearsal_commands(
        ["Verify clock"],
        env_var="APP_DB",
        validation_db_path="disposable-validation",
        cwd=tmp_path,
    )
    assert outcomes[0]["ran_at"] == WIRE
    assert outcomes[0]["stdout"] == ("" if timeout else OPAQUE)
    assert bool(error) == timeout
    assert json.loads(json.dumps(outcomes)) == outcomes


def test_native_rehearsal_result_formats_console_clock_without_a_pg_display_string():
    result = contract.RehearseResult(
        None, "clock-proof", "disposable-validation", "proof", MOMENT
    )
    assert result.rehearsed_at == MOMENT
    assert "rehearsed_at=" + WIRE in format_rehearse(result)
    unknown = contract.RehearseResult(
        None, "clock-proof", "disposable-validation", "proof", None
    )
    assert unknown.rehearsed_at is None
    assert "rehearsed_at=unknown" in format_rehearse(unknown)


@pytest.mark.parametrize("microsecond", [0, 123456])
@pytest.mark.parametrize("offset", [0, 330, -240])
def test_rehearsal_result_normalizes_native_instants(microsecond, offset):
    expected = datetime(1969, 12, 31, 23, 59, 59, microsecond, tzinfo=timezone.utc)
    supplied = expected.astimezone(timezone(timedelta(minutes=offset)))
    result = contract.RehearseResult(
        None, "clock-proof", "validation", "proof", supplied
    )
    assert result.rehearsed_at == expected
    assert result.rehearsed_at.tzinfo is timezone.utc
    assert "rehearsed_at=" + format_instant(expected) in format_rehearse(result)


@pytest.mark.parametrize(
    "bad",
    [
        "1969-12-31T23:59:59.123456Z",
        "1970-01-01T05:29:59.123456+05:30",
        datetime(1970, 1, 1),
        0,
        False,
    ],
)
def test_rehearsal_result_refuses_non_native_instants(bad):
    with pytest.raises(InvalidInstant):
        contract.RehearseResult(None, "clock-proof", "validation", "proof", bad)
