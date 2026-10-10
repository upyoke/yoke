"""Machine credentials and device authorization use native UTC instants."""

from datetime import timedelta
from uuid import uuid4

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain import machine_authorization_codes as codes
from yoke_core.domain import machine_credentials, machine_registry
from yoke_core.domain.actors import seed_human_actor


MOMENT = parse_instant("1969-12-31T05:44:59.654321+05:45")


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_machine_rotation_and_retirement_preserve_exact_instants(test_db, zone):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    actor = seed_human_actor(test_db)
    machine_id = str(uuid4())
    record, created, first = machine_credentials.register_with_credential(
        test_db,
        machine_id=machine_id,
        name="Workshop",
        actor_id=actor,
        now=MOMENT,
    )
    assert created
    assert record.registered_at == MOMENT
    assert record.retired_at is None
    assert record.to_dict()["registered_at"] == "1969-12-30T23:59:59.654321Z"
    assert record.to_dict()["retired_at"] is None
    assert first.created_at == MOMENT
    assert first.to_dict()["created_at"] == format_instant(MOMENT)
    rotated_at = MOMENT + timedelta(microseconds=1)
    _, created, second = machine_credentials.register_with_credential(
        test_db,
        machine_id=machine_id,
        name="Workshop",
        actor_id=actor,
        now=rotated_at.isoformat(),
    )
    assert not created
    assert (
        test_db.execute(
            "SELECT revoked_at FROM api_tokens WHERE id=%s", (first.token_id,)
        ).fetchone()[0]
        == rotated_at
    )
    assert second.created_at == rotated_at
    seen_at = rotated_at + timedelta(microseconds=1)
    machine_registry.touch_machine_seen(test_db, machine_id=machine_id, now=seen_at)
    assert machine_registry.get_machine(test_db, machine_id).last_seen_at == seen_at
    retired = machine_credentials.retire_with_credentials(
        test_db,
        machine_id=machine_id,
        actor_id=actor,
        now=seen_at,
    )
    assert retired.retired_at == seen_at
    assert retired.to_dict()["retired_at"] == format_instant(seen_at)
    assert (
        test_db.execute(
            "SELECT revoked_at FROM api_tokens WHERE id=%s", (second.token_id,)
        ).fetchone()[0]
        == seen_at
    )
    assert (
        test_db.execute(
            "SELECT created_at FROM api_token_audit WHERE api_token_id=%s "
            "ORDER BY id DESC LIMIT 1",
            (second.token_id,),
        ).fetchone()[0]
        == seen_at
    )


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_device_code_expiry_and_prune_keep_microseconds(test_db, monkeypatch, zone):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    clock = [MOMENT]
    monkeypatch.setattr(codes, "_now", lambda: clock[0])

    def start():
        return codes.start(
            test_db,
            origin="https://team.example",
            machine_id=str(uuid4()),
            machine_name="Workshop",
            client_key="native-expiry",
        )

    pending = start()
    expiry = MOMENT + timedelta(seconds=codes.CODE_TTL_SECONDS)
    stored = test_db.execute(
        "SELECT expires_at,consumed_at,pg_typeof(expires_at)::text "
        "FROM machine_authorization_codes WHERE user_code=%s",
        (pending["user_code"],),
    ).fetchone()
    assert stored == (expiry, None, "timestamp with time zone")
    clock[0] = expiry - timedelta(microseconds=1)
    assert (
        codes._row(test_db, "user_code", pending["user_code"])["expires_at"] == expiry
    )
    clock[0] = expiry
    with pytest.raises(codes.MachineAuthorizationError) as expired:
        codes._row(test_db, "user_code", pending["user_code"])
    assert expired.value.code == "authorization_expired"
    start()
    assert (
        test_db.execute(
            "SELECT 1 FROM machine_authorization_codes WHERE user_code=%s",
            (pending["user_code"],),
        ).fetchone()
        is None
    )


@pytest.mark.parametrize(
    "invalid",
    [
        "1969-12-31",
        "1969-12-31T23:59:59",
        "1969-12-31T23:59:59-00:00",
        MOMENT.replace(tzinfo=None),
    ],
)
def test_invalid_machine_clock_refuses_before_registration(test_db, invalid):
    actor = seed_human_actor(test_db)
    machine_id = str(uuid4())
    with pytest.raises(InvalidInstant):
        machine_credentials.register_with_credential(
            test_db,
            machine_id=machine_id,
            name="Workshop",
            actor_id=actor,
            now=invalid,
        )
    assert machine_registry.get_machine(test_db, machine_id) is None
