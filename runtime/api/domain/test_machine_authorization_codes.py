"""Personal approval, machine ownership, and one-time credential delivery."""

import pytest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from yoke_contracts.self_host_bootstrap_output import TOKEN_PREFIX
from runtime.api.domain.decision_request_test_support import decision_request_connection
from runtime.api.domain.machine_registry_test_support import (
    MACHINE_ID,
    OTHER_MACHINE_ID,
)
from yoke_core.domain import machine_authorization_codes as codes
from yoke_core.domain import machine_authorization_decisions as decisions
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
        platform="macOS",
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
    before_poll = decisions.inspect(conn, code=authorization["user_code"], actor_id=1)
    assert before_poll["machine"] == "Pat's laptop"
    assert before_poll["platform"] == "macOS"
    with pytest.raises(codes.MachineAuthorizationError, match="authorization_pending"):
        poll(conn, authorization)
    details = decisions.inspect(conn, code=authorization["user_code"], actor_id=1)
    assert details["machine"] == "Pat's laptop"
    decisions.resolve(
        conn, code=authorization["user_code"], actor_id=1, action="approve"
    )
    with pytest.raises(
        codes.MachineAuthorizationError, match="authorization_owner_mismatch"
    ):
        decisions.resolve(
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
    decisions.resolve(conn, code=authorization["user_code"], actor_id=1, action="deny")
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
        decisions.resolve(
            conn, code=authorization["user_code"], actor_id=2, action="approve"
        )
    decisions.resolve(
        conn, code=authorization["user_code"], actor_id=1, action="approve"
    )
    conn.execute("UPDATE actors SET status='disabled' WHERE id=1")
    with pytest.raises(codes.MachineAuthorizationError, match="actor_disabled"):
        poll(conn, authorization)
    assert conn.execute("SELECT count(*) FROM api_tokens").fetchone()[0] == 0


def test_mint_failure_rolls_back_consumption_and_can_retry(conn, monkeypatch):
    authorization = pending(conn)
    decisions.resolve(
        conn, code=authorization["user_code"], actor_id=1, action="approve"
    )
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
            platform="Linux",
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
    decisions.resolve(conn, code=values[0]["user_code"], actor_id=1, action="approve")
    poll(conn, values[0])
    assert pending(conn)["device_code"]


def test_inspection_retains_expired_facts_but_decision_refuses(conn):
    authorization = pending(conn)
    conn.execute(
        "UPDATE machine_authorization_codes SET expires_at='2000-01-01T00:00:00Z'"
    )
    details = decisions.inspect(conn, code=authorization["user_code"], actor_id=1)
    assert details["expires_at"] == "2000-01-01T00:00:00.000000Z"
    with pytest.raises(codes.MachineAuthorizationError, match="authorization_expired"):
        decisions.resolve(
            conn, code=authorization["user_code"], actor_id=1, action="approve"
        )


def test_inspection_retains_approved_facts_after_delivery(conn):
    authorization = pending(conn)
    decisions.resolve(
        conn, code=authorization["user_code"], actor_id=1, action="approve"
    )
    poll(conn, authorization)
    assert (
        decisions.inspect(conn, code=authorization["user_code"], actor_id=1)["decision"]
        == "approve"
    )
    with pytest.raises(
        codes.MachineAuthorizationError, match="authorization_unavailable"
    ):
        decisions.inspect(conn, code="UNKNOWN", actor_id=1)


@pytest.mark.parametrize("action,opposite", [("approve", "deny"), ("deny", "approve")])
def test_decision_binds_actor_and_replays_without_inbox_mirror(conn, action, opposite):
    code = pending(conn)["user_code"]
    assert decisions.resolve(conn, code=code.lower(), actor_id=1, action=action) == {
        "decision": action
    }
    stored = tuple(
        conn.execute(
            "SELECT actor_id,decision,decided_at FROM machine_authorization_codes"
        ).fetchone()
    )
    assert stored[:2] == (1, action)
    assert stored[2] is not None
    assert decisions.resolve(conn, code=code, actor_id=1, action=action) == {
        "decision": action
    }
    with pytest.raises(
        codes.MachineAuthorizationError, match="authorization_already_decided"
    ):
        decisions.resolve(conn, code=code, actor_id=1, action=opposite)
    with pytest.raises(
        codes.MachineAuthorizationError, match="authorization_owner_mismatch"
    ):
        decisions.resolve(conn, code=code, actor_id=5, action=action)
    assert (
        tuple(
            conn.execute(
                "SELECT actor_id,decision,decided_at FROM machine_authorization_codes"
            ).fetchone()
        )
        == stored
    )
    assert conn.execute("SELECT count(*) FROM decision_requests").fetchone()[0] == 0


@pytest.mark.parametrize(
    "kind,status,error",
    [
        ("human", "disabled", "actor_disabled"),
        ("machine", "active", "authorization_human_required"),
        ("system", "active", "authorization_human_required"),
    ],
)
def test_only_active_human_members_can_resolve(conn, kind, status, error):
    code = pending(conn)["user_code"]
    conn.execute("UPDATE actors SET kind=?,status=? WHERE id=1", (kind, status))
    with pytest.raises(codes.MachineAuthorizationError, match=error):
        decisions.resolve(conn, code=code, actor_id=1, action="approve")
    assert tuple(
        conn.execute(
            "SELECT actor_id,decision,decided_at FROM machine_authorization_codes"
        ).fetchone()
    ) == (None, None, None)


@pytest.mark.parametrize("code", ["ABCDE-F1234", "ABCDEF1234"])
def test_in_flight_long_codes_still_resolve(conn, code):
    authorization = pending(conn)
    conn.execute("UPDATE machine_authorization_codes SET user_code=?", (code,))
    assert decisions.inspect(conn, code=code, actor_id=1)["code"] == code
    decisions.resolve(conn, code=code, actor_id=1, action="approve")
    assert poll(conn, authorization)["token"]


def test_concurrent_opposite_decisions_have_one_winner(tmp_path):
    from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
    from yoke_core.domain.api_tokens import bootstrap_admin_token

    with init_test_db(tmp_path) as token:
        with connect_test_db(token) as worker:
            actor_id = bootstrap_admin_token(worker).actor_id
            code = pending(worker)["user_code"]
        ready = Barrier(2)

        def decide(action):
            with connect_test_db(token) as worker:
                ready.wait(timeout=10)
                try:
                    return decisions.resolve(
                        worker, code=code, actor_id=actor_id, action=action
                    )["decision"]
                except codes.MachineAuthorizationError as error:
                    return error.code

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(decide, ["approve", "deny"]))
        assert results.count("authorization_already_decided") == 1
        with connect_test_db(token) as worker:
            stored = worker.execute(
                "SELECT actor_id,decision,decided_at FROM machine_authorization_codes"
            ).fetchone()
            assert stored[0] == actor_id
            assert stored[1] in results
            assert stored[2] is not None


def test_boot_converges_decision_columns_for_born_and_existing_universes(tmp_path):
    from runtime.api.domain import test_boot_schema_column_convergence as boot
    from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
    from yoke_core.domain.schema_init import converge_core_schema

    with init_test_db(
        tmp_path, apply_schema=boot._apply_complete_control_plane_schema
    ) as token:
        with connect_test_db(token) as worker:
            names = {"decision", "decided_at"}
            assert names <= boot._column_map(worker)["machine_authorization_codes"]
            authorization = pending(worker)
            worker.execute(
                "ALTER TABLE machine_authorization_codes DROP COLUMN decision"
            )
            worker.execute(
                "ALTER TABLE machine_authorization_codes DROP COLUMN decided_at"
            )
            worker.commit()
            converge_core_schema(worker)
            converge_core_schema(worker)
            assert names <= boot._column_map(worker)["machine_authorization_codes"]
            assert tuple(
                worker.execute(
                    "SELECT user_code,decision,decided_at FROM machine_authorization_codes"
                ).fetchone()
            ) == (authorization["user_code"], None, None)
