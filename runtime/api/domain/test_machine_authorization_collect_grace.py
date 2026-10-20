"""An approval made before expiry is collected after it, within the grace window."""

from datetime import timedelta

import pytest

from runtime.api.domain.decision_request_test_support import decision_request_connection
from runtime.api.domain.machine_registry_test_support import MACHINE_ID
from yoke_contracts.machine_authorization import (
    CODE_TTL_SECONDS,
    COLLECT_GRACE_SECONDS,
)
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import machine_authorization_codes as codes
from yoke_core.domain import machine_authorization_decisions as decisions
from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.external_identity_schema import create_external_identity_tables
from yoke_core.domain.machine_authorization_schema import (
    create_machine_authorization_table,
)
from yoke_core.domain.machine_registry_schema import ensure_machine_registry_schema

START = parse_instant("2026-10-20T02:48:13Z")
EXPIRY = START + timedelta(seconds=CODE_TTL_SECONDS)
GRACE = timedelta(seconds=COLLECT_GRACE_SECONDS)


@pytest.fixture()
def clock(monkeypatch):
    now = [START]
    monkeypatch.setattr(codes, "_now", lambda: now[0])
    monkeypatch.setattr(decisions, "_now", lambda: now[0])
    return now


@pytest.fixture()
def conn(clock):
    with decision_request_connection() as value:
        create_auth_tables(value)
        create_external_identity_tables(value)
        ensure_machine_registry_schema(value)
        create_machine_authorization_table(value)
        value.execute("INSERT INTO actor_org_roles VALUES (1, 1, 4, 'now')")
        value.commit()
        yield value


def start(conn, client_key="client", machine_id=MACHINE_ID):
    return codes.start(
        conn,
        origin="https://team.example",
        machine_id=machine_id,
        machine_name="Test Mac",
        platform="macOS",
        client_key=client_key,
    )


def poll(conn, authorization):
    return codes.poll(
        conn,
        device_code=authorization["device_code"],
        machine_id=MACHINE_ID,
        machine_name="Test Mac",
        origin="https://team.example",
    )


def approve(conn, authorization):
    decisions.resolve(
        conn, code=authorization["user_code"], actor_id=1, action="approve"
    )


def machines(conn):
    return conn.execute("SELECT count(*) FROM machines").fetchone()[0]


def test_approval_five_seconds_before_expiry_is_collected_after_it(conn, clock):
    authorization = start(conn)
    clock[0] = EXPIRY - timedelta(seconds=5)
    approve(conn, authorization)
    clock[0] = EXPIRY + timedelta(minutes=2)
    state = decisions.inspect(conn, code=authorization["user_code"], actor_id=1)
    assert state["state"] == "approved"

    credential = poll(conn, authorization)

    assert credential["token"]
    assert machines(conn) == 1
    with pytest.raises(codes.MachineAuthorizationError, match="authorization_consumed"):
        poll(conn, authorization)


def test_approval_never_collected_is_named_after_the_grace_window(conn, clock):
    authorization = start(conn)
    clock[0] = EXPIRY - timedelta(seconds=5)
    approve(conn, authorization)
    clock[0] = EXPIRY + GRACE + timedelta(seconds=1)

    with pytest.raises(codes.MachineAuthorizationError) as refused:
        poll(conn, authorization)

    assert refused.value.code == "authorization_expired"
    assert "approval_uncollected" in str(refused.value)
    state = decisions.inspect(conn, code=authorization["user_code"], actor_id=1)
    assert state["state"] == "uncollected"
    assert machines(conn) == 0


def test_expiry_still_ends_an_unanswered_code_and_late_approval(conn, clock):
    authorization = start(conn)
    clock[0] = EXPIRY + timedelta(seconds=1)
    with pytest.raises(codes.MachineAuthorizationError, match="authorization_expired"):
        approve(conn, authorization)
    with pytest.raises(codes.MachineAuthorizationError) as refused:
        poll(conn, authorization)
    assert "approval_uncollected" not in str(refused.value)
    assert machines(conn) == 0


def test_purge_keeps_codes_through_grace_and_counts_only_live_codes(conn, clock):
    approved = start(conn)
    approve(conn, approved)
    for _ in range(codes.CLIENT_PENDING_CODES - 1):
        start(conn)
    clock[0] = EXPIRY + timedelta(seconds=1)
    # Expired codes no longer hold this client's pending capacity.
    fresh = start(conn)
    assert poll(conn, approved)["token"]
    clock[0] = EXPIRY + GRACE
    newest = start(conn, client_key="other")
    remaining = conn.execute(
        "SELECT user_code FROM machine_authorization_codes"
    ).fetchall()
    assert {row[0] for row in remaining} == {fresh["user_code"], newest["user_code"]}
