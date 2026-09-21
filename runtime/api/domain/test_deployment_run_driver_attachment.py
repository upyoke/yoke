"""Live driver attachment on a deployment run is a shared, named fact."""

from __future__ import annotations

import pytest

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

NOW = "2026-09-21T12:00:00Z"
LATER = "2026-09-21T12:01:00Z"
STALE = "2026-09-21T12:10:01Z"


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
        assert second.attached_at == NOW
        assert second.heartbeat_at == LATER
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
        assert live_attachment_for_run(conn, run_id_value=run_id, now=STALE) == recovered
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
        found = live_attachment_for_capture(
            conn, progress_capture=capture, now=NOW
        )
        assert found == recorded
        assert live_attachment_for_capture(
            conn, progress_capture="/tmp/other.log", now=NOW
        ) is None
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
