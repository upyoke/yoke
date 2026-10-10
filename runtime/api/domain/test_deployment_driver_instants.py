"""Driver custody and QA wake reads keep native instants at their boundaries."""

from datetime import datetime, timedelta
import json

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain import deployment_run_driver_attachment as driver
from yoke_core.domain import deployment_qa_stage_wake_state as wake


QUALIFIED = "1970-01-01T05:44:59.123456+05:45"
CANONICAL = "1969-12-31T23:59:59.123456Z"
INSTANT = parse_instant(QUALIFIED)


def _attachment(clock=INSTANT):
    return driver.DriverAttachment(
        run_id="run-native-driver",
        session_id="session-native-driver",
        pid=42,
        attached_at=clock,
        heartbeat_at=clock,
        phase=driver.PHASE_FREEZING_SOURCE,
        progress_capture="/tmp/2026-10-08-driver.log",
        machine_id="machine-native-driver",
    )


def test_driver_clock_is_native_and_wire_only_at_declared_fields() -> None:
    attachment = _attachment()
    assert attachment.attached_at == INSTANT
    assert attachment.heartbeat_at == INSTANT
    payload = json.loads(driver._serialize(attachment))
    assert payload["attached_at"] == CANONICAL
    assert payload["heartbeat_at"] == CANONICAL
    assert payload["progress_capture"] == "/tmp/2026-10-08-driver.log"
    assert driver.parse_attachment(attachment.run_id, json.dumps(payload)) == attachment
    assert attachment.as_dict()["attached_at"] == CANONICAL
    assert CANONICAL in driver.format_refusal(attachment.run_id, attachment)


def test_live_heartbeat_preserves_inclusive_microsecond_boundary() -> None:
    attachment = _attachment()
    boundary = INSTANT + driver.LIVE_HEARTBEAT
    assert driver.is_live(attachment, now=boundary)
    assert not driver.is_live(attachment, now=boundary + timedelta(microseconds=1))
    assert driver.is_live(attachment, now=INSTANT)


@pytest.mark.parametrize(
    "invalid",
    [None, "", "1970-01-01", QUALIFIED, CANONICAL, 0, False, datetime(1970, 1, 1)],
)
def test_bad_driver_clock_refuses_before_database_or_liveness(invalid) -> None:
    class UnusedConnection:
        def execute(self, *_args):
            pytest.fail("database read before clock validation")

    conn = UnusedConnection()
    with pytest.raises(InvalidInstant):
        _attachment(invalid)
    with pytest.raises(InvalidInstant):
        driver.is_live(_attachment(), now=invalid)
    with pytest.raises(InvalidInstant):
        driver.live_attachment_for_run(conn, run_id_value="run", now=invalid)
    with pytest.raises(InvalidInstant):
        driver.live_attachment_for_capture(
            conn, progress_capture="/tmp/log", now=invalid
        )
    if invalid is not None:
        with pytest.raises(InvalidInstant):
            driver.attach_driver(
                conn,
                "run",
                session_id="session",
                pid=42,
                phase=driver.PHASE_EXECUTING,
                now=invalid,
            )


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_wake_notice_retains_native_clock_in_each_database_zone(test_db, zone) -> None:
    from runtime.api.steering_fleet_test_helpers import (
        PROJECT_ID,
        WORKER_SESSION,
        seed_message,
        seed_steering_scope,
    )
    from yoke_core.domain.deployment_qa_stage_wake import stage_wait_idempotency_key

    seed_steering_scope(test_db)
    test_db.execute("SELECT set_config('TimeZone', %s, true)", (zone,))
    seed_message(
        test_db,
        "native-wake",
        sender=None,
        to=WORKER_SESSION,
        at=CANONICAL,
        state="acknowledged",
        idempotency_key=stage_wait_idempotency_key(
            "run-native", "item-qa", 1, "digest"
        ),
    )
    notices = wake._latest_notices(test_db, run_id="run-native", stage_name="item-qa")
    assert notices[1][1] == INSTANT
    assert isinstance(notices[1][1], datetime)
    assert wake.member_wake_states(
        test_db,
        run_id="run-native",
        stage_name="item-qa",
        item_ids=[1],
        project_id=PROJECT_ID,
        driver_live=False,
    ) == {1: "woken 23:59Z, acknowledged"}
