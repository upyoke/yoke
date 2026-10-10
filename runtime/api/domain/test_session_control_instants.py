"""Launch and relay clocks retain native microseconds through real PostgreSQL."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant
from yoke_core.domain.session_launch_cursor import (
    decode_launch_cursor,
    encode_launch_cursor,
)
from yoke_core.domain.session_launch_execution import claim_assigned_launch
from yoke_core.domain.session_launch_projection import public_launch_record
from yoke_core.domain.session_launch_registration_candidate import (
    registration_binding_window,
)
from yoke_core.domain.session_launch_request_storage import insert_launch_request
from yoke_core.domain.session_launch_store import (
    get_launch,
    insert_instruction_message,
    update_launch,
)
from yoke_core.domain.session_launch_types import (
    LaunchAuthorization,
    LaunchPreview,
    LaunchRequest,
    EligibleRelay,
)
from yoke_core.domain.session_relay_storage import (
    heartbeat_relay,
    mark_relay_batch,
    require_relay_batch,
)
from yoke_core.domain.session_relay_types import RelayHeartbeat, SessionRelayError


INSTANT = datetime(1969, 12, 31, 23, 59, 59, 123456, timezone.utc)


@pytest.fixture
def fleet_identity(test_db):
    actor_id = test_db.execute(
        "INSERT INTO actors (kind,name,created_at) VALUES (%s,%s,%s) RETURNING id",
        ("human", "Native fleet owner", INSTANT),
    ).fetchone()[0]
    project_id = test_db.execute(
        "SELECT id FROM projects ORDER BY id LIMIT 1"
    ).fetchone()[0]
    machine_id = str(uuid4())
    return actor_id, project_id, machine_id


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_relay_lease_edge_is_native_exact_and_half_open(test_db, fleet_identity, zone):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    actor_id, project_id, machine_id = fleet_identity
    relay_id = f"machine:{machine_id}"
    heartbeat = RelayHeartbeat(
        relay_id,
        actor_id,
        machine_id,
        "native-host",
        "0.1.1",
        {"codex-cli": "0.148.0a15"},
        (project_id,),
    )
    connected = heartbeat_relay(
        test_db, heartbeat, state="active", next_poll_seconds=1, now=INSTANT
    )
    assert connected == INSTANT + timedelta(seconds=2)
    edge = INSTANT + timedelta(seconds=90, microseconds=1)
    mark_relay_batch(
        test_db,
        relay_id=relay_id,
        batch_id="native-batch",
        expires_at=edge,
        now=INSTANT,
    )
    connected = heartbeat_relay(
        test_db, heartbeat, state="active", next_poll_seconds=1, now=INSTANT
    )
    assert connected == edge
    stored, kind = test_db.execute(
        "SELECT lease_expires_at,pg_typeof(lease_expires_at)::text FROM session_relays WHERE relay_id=%s",
        (relay_id,),
    ).fetchone()
    assert stored == edge
    assert kind == "timestamp with time zone"
    require_relay_batch(
        test_db, relay_id=relay_id, now=edge - timedelta(microseconds=1)
    )
    with pytest.raises(SessionRelayError) as caught:
        require_relay_batch(test_db, relay_id=relay_id, now=edge)
    assert caught.value.code == "relay_lease_expired"


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_launch_claim_and_terminal_delivery_keep_native_instants(
    test_db, fleet_identity, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    actor_id, project_id, machine_id = fleet_identity
    relay_id = f"machine:{machine_id}"
    launch_id, message_id = str(uuid4()), str(uuid4())
    deadline = INSTANT + timedelta(minutes=10)
    insert_instruction_message(
        test_db,
        message_id=message_id,
        launch_id=launch_id,
        actor_id=actor_id,
        session_id=None,
        sender_surface="cli",
        project_id=project_id,
        body="native launch",
        created_at=INSTANT,
        expires_at=deadline,
    )
    relay = EligibleRelay(relay_id, machine_id, "codex-cli", "0.148.0a15", INSTANT)
    inserted = insert_launch_request(
        test_db,
        launch_id=launch_id,
        message_id=message_id,
        auth=LaunchAuthorization(actor_id, None, True),
        request=LaunchRequest(project_id, "codex-cli", "native launch", str(uuid4())),
        preview=LaunchPreview("launchable", "codex-cli", (relay,), relay),
        created_at=INSTANT,
        deadline_at=deadline,
    )
    assert inserted
    claim_time = INSTANT + timedelta(seconds=1, microseconds=1)
    claim = claim_assigned_launch(
        test_db,
        launch_id=launch_id,
        relay_id=relay_id,
        machine_id=machine_id,
        now=claim_time,
    )
    assert claim.launch.created_at == INSTANT
    assert claim.launch.launching_at == claim_time
    assert claim.lease_expires_at == claim_time + timedelta(seconds=300)
    wire = public_launch_record(claim.launch)
    assert wire["created_at"] == format_instant(INSTANT)
    assert wire["launching_at"] == format_instant(claim_time)
    assert wire["completed_at"] is None
    assert decode_launch_cursor(encode_launch_cursor(INSTANT, launch_id)) == (
        INSTANT,
        launch_id,
    )
    completed = claim_time + timedelta(microseconds=1)
    update_launch(test_db, launch_id, state="failed", completed_at=completed)
    assert get_launch(test_db, launch_id).completed_at == completed
    message_cancel = test_db.execute(
        "SELECT cancelled_at FROM session_messages WHERE message_id=%s", (message_id,)
    ).fetchone()[0]
    assert message_cancel == completed


def test_registration_window_retains_fractional_half_open_bound():
    start, end = registration_binding_window(
        INSTANT, INSTANT + timedelta(seconds=2), {"native_launch_bound_seconds": 1}
    )
    assert start == INSTANT
    assert end == INSTANT + timedelta(seconds=1)
    assert end.microsecond == INSTANT.microsecond


@pytest.mark.parametrize(
    "value", ["", "2026-10-08", "2026-10-08T00:00:00", 0, datetime(2026, 10, 8)]
)
def test_registration_window_refuses_ambiguous_instant(value):
    with pytest.raises(InvalidInstant, match="invalid_instant"):
        registration_binding_window(value, INSTANT, {"native_launch_bound_seconds": 1})
