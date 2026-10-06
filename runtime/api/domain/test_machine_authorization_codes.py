"""Personal approval, machine ownership, and one-time credential delivery."""

import pytest
from yoke_contracts.self_host_bootstrap_output import TOKEN_PREFIX
from runtime.api.domain.decision_request_test_support import decision_request_connection
from runtime.api.domain.machine_registry_test_support import (
    MACHINE_ID,
    OTHER_MACHINE_ID,
)
from yoke_core.domain import machine_authorization_codes as codes
from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.external_identity_schema import create_external_identity_tables
from yoke_core.domain.machine_authorization_schema import (
    create_machine_authorization_table,
)
from yoke_core.domain.machine_registry_schema import ensure_machine_registry_schema

ORIGIN = "https://team.example"


@pytest.fixture()
def conn():
    with decision_request_connection() as value:
        create_auth_tables(value)
        create_external_identity_tables(value)
        ensure_machine_registry_schema(value)
        create_machine_authorization_table(value)
        value.execute("INSERT INTO actor_org_roles VALUES (1, 1, 4, 'now')")
        value.commit()
        yield value


def pending(conn, client_key="client"):
    return codes.start(
        conn,
        origin=ORIGIN,
        machine_id=MACHINE_ID,
        machine_name="Pat's laptop",
        client_key=client_key,
    )


def poll(conn, authorization, **kwargs):
    return codes.poll(
        conn,
        device_code=authorization["device_code"],
        machine_id=kwargs.get("machine_id", MACHINE_ID),
        machine_name="Pat's laptop",
        origin=ORIGIN,
    )


def test_member_approves_own_machine_and_delivery_consumes_code(conn):
    authorization = pending(conn)
    row = conn.execute(
        "SELECT device_hash,org_id FROM machine_authorization_codes"
    ).fetchone()
    assert authorization["device_code"] not in row[0]
    assert row[1] == 1
    with pytest.raises(codes.MachineAuthorizationError, match="authorization_pending"):
        poll(conn, authorization)
    details = codes.inspect(conn, code=authorization["user_code"], actor_id=1)
    assert details["machine"] == "Pat's laptop"
    codes.resolve(conn, code=authorization["user_code"], actor_id=1, action="approve")
    with pytest.raises(
        codes.MachineAuthorizationError, match="authorization_owner_mismatch"
    ):
        codes.resolve(
            conn, code=authorization["user_code"], actor_id=5, action="approve"
        )
    credential = poll(conn, authorization)
    assert credential["api_url"] == ORIGIN
    assert credential["org"] == "default"
    assert credential["token"].startswith(TOKEN_PREFIX)
    assert conn.execute("SELECT owner_actor_id FROM machines").fetchone()[0] == 1
    assert tuple(
        conn.execute("SELECT actor_id,machine_id FROM api_tokens").fetchone()
    ) == (1, MACHINE_ID)
    with pytest.raises(codes.MachineAuthorizationError, match="authorization_consumed"):
        poll(conn, authorization)
    assert conn.execute("SELECT count(*) FROM api_tokens").fetchone()[0] == 1


def test_denied_expired_and_mismatched_machine_codes_never_mint(conn):
    authorization = pending(conn)
    with pytest.raises(
        codes.MachineAuthorizationError, match="machine_identity_mismatch"
    ):
        poll(conn, authorization, machine_id=OTHER_MACHINE_ID)
    codes.resolve(conn, code=authorization["user_code"], actor_id=1, action="deny")
    with pytest.raises(codes.MachineAuthorizationError, match="authorization_denied"):
        poll(conn, authorization)
    conn.execute(
        "UPDATE machine_authorization_codes SET expires_at='2000-01-01T00:00:00Z'"
    )
    with pytest.raises(codes.MachineAuthorizationError, match="authorization_expired"):
        poll(conn, authorization)
    assert conn.execute("SELECT count(*) FROM api_tokens").fetchone()[0] == 0


def test_nonmember_and_disabled_approver_cannot_get_credential(conn):
    authorization = pending(conn)
    with pytest.raises(
        codes.MachineAuthorizationError, match="organization_membership_required"
    ):
        codes.resolve(
            conn, code=authorization["user_code"], actor_id=2, action="approve"
        )
    codes.resolve(conn, code=authorization["user_code"], actor_id=1, action="approve")
    conn.execute("UPDATE actors SET status='disabled' WHERE id=1")
    with pytest.raises(codes.MachineAuthorizationError, match="actor_disabled"):
        poll(conn, authorization)
    assert conn.execute("SELECT count(*) FROM api_tokens").fetchone()[0] == 0


def test_mint_failure_rolls_back_consumption_and_can_retry(conn, monkeypatch):
    authorization = pending(conn)
    codes.resolve(conn, code=authorization["user_code"], actor_id=1, action="approve")
    real_mint = codes.register_with_credential

    def broken(*args, **kwargs):
        raise RuntimeError("database disconnected")

    monkeypatch.setattr(codes, "register_with_credential", broken)
    with pytest.raises(RuntimeError), conn:
        poll(conn, authorization)
    assert (
        conn.execute("SELECT consumed_at FROM machine_authorization_codes").fetchone()[
            0
        ]
        is None
    )
    monkeypatch.setattr(codes, "register_with_credential", real_mint)
    assert poll(conn, authorization)["token"]


def test_pending_store_is_bounded_and_expires_without_affecting_decisions(conn):
    for client in range(16):
        for _ in range(8):
            pending(conn, client_key=str(client))
    with pytest.raises(codes.MachineAuthorizationError, match="authorization_capacity"):
        pending(conn, client_key="fresh-client")
    conn.execute(
        "UPDATE machine_authorization_codes SET expires_at='2000-01-01T00:00:00Z'"
    )
    assert pending(conn)["device_code"]
    assert (
        conn.execute("SELECT count(*) FROM machine_authorization_codes").fetchone()[0]
        == 1
    )


def test_one_client_cannot_fill_the_server_by_changing_machine_identity(conn):
    for _ in range(codes.CLIENT_PENDING_CODES):
        pending(conn, client_key="attacker")
    with pytest.raises(
        codes.MachineAuthorizationError, match="authorization_client_capacity"
    ):
        codes.start(
            conn,
            origin=ORIGIN,
            machine_id=OTHER_MACHINE_ID,
            machine_name="new id",
            client_key="attacker",
        )
    conn.rollback()
    assert pending(conn, client_key="another-client")["device_code"]
    assert (
        conn.execute("SELECT count(*) FROM machine_authorization_codes").fetchone()[0]
        == codes.CLIENT_PENDING_CODES + 1
    )


def test_consumed_codes_free_client_capacity(conn):
    values = [pending(conn) for _ in range(codes.CLIENT_PENDING_CODES)]
    codes.resolve(conn, code=values[0]["user_code"], actor_id=1, action="approve")
    poll(conn, values[0])
    assert pending(conn)["device_code"]
