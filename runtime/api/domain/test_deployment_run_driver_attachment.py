"""Live driver attachment on a deployment run is a shared, named fact."""

from __future__ import annotations

import pytest

from yoke_contracts.timestamps import parse_instant

from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain import deployment_runs as dr
from yoke_core.domain.deployment_run_driver_attachment import (
    PHASE_EXECUTING,
    PHASE_FREEZING_SOURCE,
    DriverAlreadyAttached,
    attach_driver,
    live_attachment_for_capture,
    live_attachment_for_run,
    release_driver,
)

pytest_plugins = ["runtime.api.deployment_runs_test_db"]

NOW = parse_instant("2026-09-21T12:00:00Z")
LATER = parse_instant("2026-09-21T12:01:00Z")
STALE = parse_instant("2026-09-21T12:10:01Z")


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
@pytest.mark.parametrize("microsecond", [0, 123456])
def test_run_notice_resolves_native_driver_clock(
    db_path, monkeypatch, zone, microsecond
):
    from yoke_core.domain import deployment_run_driver_notice as notice

    stamp = parse_instant("1970-01-01T05:29:59+05:30").replace(microsecond=microsecond)
    monkeypatch.setattr(notice, "utc_now", lambda: stamp)
    monkeypatch.setattr(notice, "_session_actor", lambda conn, session: 1)
    run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    conn = connect_test_db(db_path)
    try:
        conn.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
        conn.commit()
        attach_driver(
            conn, run_id, session_id="sess-a", pid=11, phase=PHASE_EXECUTING, now=stamp
        )
        conn.commit()
        assert notice.resolve_run_driver_recipient(
            conn, run_id=run_id, project_id=1
        ) == ("sess-a", 1, "driver")
        found = live_attachment_for_run(conn, run_id_value=run_id, now=stamp)
        assert found.attached_at == stamp
        assert found.heartbeat_at == stamp
        assert conn.execute("SHOW TimeZone").fetchone()[0] == zone
    finally:
        conn.close()


def test_a_second_live_driver_is_refused_by_name(db_path: str) -> None:
    run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    conn = connect_test_db(db_path)
    try:
        first = attach_driver(
            conn,
            run_id,
            session_id="sess-a",
            pid=11,
            phase=PHASE_FREEZING_SOURCE,
            progress_capture="/tmp/progress.log",
            now=NOW,
        )
        conn.commit()
        assert first is not None
        with pytest.raises(DriverAlreadyAttached) as raised:
            attach_driver(
                conn,
                run_id,
                session_id="sess-b",
                pid=22,
                phase=PHASE_EXECUTING,
                now=NOW,
            )
        text = str(raised.value)
        assert "sess-a" in text
        assert "pid 11" in text
        assert PHASE_FREEZING_SOURCE in text
        assert "/tmp/progress.log" in text
    finally:
        conn.close()


def test_the_same_process_refreshes_heartbeat_and_phase(db_path: str) -> None:
    run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    conn = connect_test_db(db_path)
    try:
        first = attach_driver(
            conn,
            run_id,
            session_id="sess-a",
            pid=11,
            phase=PHASE_FREEZING_SOURCE,
            now=NOW,
        )
        conn.commit()
        second = attach_driver(
            conn,
            run_id,
            session_id="sess-a",
            pid=11,
            phase=PHASE_EXECUTING,
            progress_capture="/tmp/progress.log",
            now=LATER,
        )
        conn.commit()
        assert first is not None and second is not None
        assert second.attached_at == parse_instant(NOW)
        assert second.heartbeat_at == parse_instant(LATER)
        assert second.phase == PHASE_EXECUTING
        assert second.progress_capture == "/tmp/progress.log"
    finally:
        conn.close()


def test_a_stale_heartbeat_lets_another_process_re_drive(db_path: str) -> None:
    run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    conn = connect_test_db(db_path)
    try:
        attach_driver(
            conn,
            run_id,
            session_id="sess-a",
            pid=11,
            phase=PHASE_FREEZING_SOURCE,
            now=NOW,
        )
        conn.commit()
        recovered = attach_driver(
            conn,
            run_id,
            session_id="sess-b",
            pid=22,
            phase=PHASE_EXECUTING,
            now=STALE,
        )
        conn.commit()
        assert recovered is not None
        assert recovered.session_id == "sess-b"
        assert recovered.pid == 22
        assert (
            live_attachment_for_run(conn, run_id_value=run_id, now=STALE) == recovered
        )
    finally:
        conn.close()


def test_capture_lookup_names_the_live_writer(db_path: str) -> None:
    run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    conn = connect_test_db(db_path)
    capture = "/tmp/watch-progress.log"
    try:
        recorded = attach_driver(
            conn,
            run_id,
            session_id="sess-a",
            pid=11,
            phase=PHASE_FREEZING_SOURCE,
            progress_capture=capture,
            now=NOW,
        )
        conn.commit()
        found = live_attachment_for_capture(conn, progress_capture=capture, now=NOW)
        assert found == recorded
        assert (
            live_attachment_for_capture(
                conn, progress_capture="/tmp/other.log", now=NOW
            )
            is None
        )
    finally:
        conn.close()


def test_only_the_holding_process_can_release(db_path: str) -> None:
    run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    conn = connect_test_db(db_path)
    try:
        attach_driver(
            conn,
            run_id,
            session_id="sess-a",
            pid=11,
            phase=PHASE_EXECUTING,
            now=NOW,
        )
        conn.commit()
        assert release_driver(conn, run_id, session_id="sess-b", pid=11) is False
        assert live_attachment_for_run(conn, run_id_value=run_id, now=NOW) is not None
        assert release_driver(conn, run_id, session_id="sess-a", pid=11) is True
        conn.commit()
        assert live_attachment_for_run(conn, run_id_value=run_id, now=NOW) is None
    finally:
        conn.close()


def test_attach_proceeds_when_the_column_has_not_converged(db_path: str) -> None:
    run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    conn = connect_test_db(db_path)
    try:
        conn.execute("ALTER TABLE deployment_runs DROP COLUMN driver_attachment")
        conn.commit()
        recorded = attach_driver(
            conn,
            run_id,
            session_id="sess-a",
            pid=11,
            phase=PHASE_FREEZING_SOURCE,
            now=NOW,
        )
        assert recorded is None
        assert live_attachment_for_run(conn, run_id_value=run_id, now=NOW) is None
    finally:
        conn.close()


MACHINE = "6f1c2b9e-0d4a-4c1e-9a52-3b7e8d1f0a11"
OTHER_MACHINE = "a0e4d7c3-58b1-4f2a-b6e9-91c0d2f3e4a5"


@pytest.mark.parametrize(
    ("machine_id", "exited_driver_pid", "supersedes"),
    [
        (MACHINE, 11, True),
        # Another machine cannot see this pid; its heartbeat still rules.
        (OTHER_MACHINE, 11, False),
        # Naming a different pid says nothing about the recorded driver.
        (MACHINE, 12, False),
        # A caller that names no machine proves nothing about one.
        ("", 11, False),
    ],
)
def test_an_exited_driver_is_superseded_only_from_its_own_machine(
    db_path: str, machine_id: str, exited_driver_pid: int, supersedes: bool
) -> None:
    run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
    conn = connect_test_db(db_path)
    try:
        attach_driver(
            conn,
            run_id,
            session_id="sess-a",
            pid=11,
            phase=PHASE_EXECUTING,
            machine_id=MACHINE,
            now=NOW,
        )
        conn.commit()

        def _re_drive():
            return attach_driver(
                conn,
                run_id,
                session_id="sess-b",
                pid=22,
                phase=PHASE_EXECUTING,
                machine_id=machine_id,
                exited_driver_pid=exited_driver_pid,
                now=LATER,
            )

        if not supersedes:
            with pytest.raises(DriverAlreadyAttached) as raised:
                _re_drive()
            assert raised.value.current.machine_id == MACHINE
            assert raised.value.current.pid == 11
            return
        recovered = _re_drive()
        conn.commit()
        assert recovered is not None
        assert (recovered.session_id, recovered.pid) == ("sess-b", 22)
        assert recovered.machine_id == machine_id
        assert recovered.attached_at == parse_instant(LATER)
    finally:
        conn.rollback()
        conn.close()
