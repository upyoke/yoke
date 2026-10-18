"""Teammate admission transactions, replay refusal and one-time redemption."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from yoke_contracts.timestamps import utc_now
from yoke_core.domain import machine_credentials
from yoke_core.domain import teammate_invite_codes as invites
from yoke_core.domain.actor_permissions import seed_roles_and_permissions
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.api_tokens import verify_token
from yoke_core.domain.external_identity_schema import create_external_identity_tables

from runtime.api.fixtures import pg_testdb


@pytest.fixture
def store(test_db):
    seed_roles_and_permissions(test_db)
    inviter = seed_human_actor(test_db, "Inviter")
    database = test_db.execute("SELECT current_database()").fetchone()[0]
    test_db.commit()
    with pg_testdb.connect_test_database(database) as observer:
        yield test_db, observer, inviter, database


def _create(store, **kwargs):
    conn, _, inviter, _ = store
    return invites.create_invite(
        conn, name="Teammate", inviter_actor_id=inviter, **kwargs
    )


def _counts(conn):
    return tuple(
        conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("actors", "actor_org_roles", "teammate_invite_codes")
    )


def _redeem(conn, code, machine_id=None):
    return invites.redeem_invite(
        conn,
        code=code,
        machine_id=machine_id or str(uuid4()),
        machine_name="Laptop",
        origin="https://team.example/",
    )


def _assert_refusal(code, operation, status=None):
    with pytest.raises(invites.TeammateInviteError) as caught:
        operation()
    assert caught.value.code == code
    assert str(caught.value)
    if status:
        assert caught.value.status == status


@pytest.mark.parametrize(
    "value",
    ["ABCD", "beta_123", "yinv_abc", "x" * 37, "yinv_" + "0" * 32, "yinv_" + "a" * 33],
)
def test_parse_refuses_other_code_families_and_malformed_codes(value):
    _assert_refusal(
        "invite_code_invalid", lambda: invites.parse_invite_code(value), 404
    )


@pytest.mark.parametrize("state", ["expired", "revoked", "consumed"])
def test_state_refusals_and_list_filter(store, state):
    conn, observer, inviter, _ = store
    created = _create(store)
    if state == "revoked":
        invites.revoke_invite(
            conn, invite_id=created.invite["invite_id"], actor_id=inviter
        )
    elif state == "consumed":
        _redeem(conn, created.code)
    else:
        conn.execute(
            "UPDATE teammate_invite_codes SET expires_at=%s",
            (utc_now() - timedelta(seconds=1),),
        )
        conn.commit()
    _assert_refusal(f"invite_{state}", lambda: _redeem(conn, created.code), 410)
    assert invites.list_invites(conn) == []
    assert invites.list_invites(conn, include_used=True)[0]["state"] == state
    assert observer.execute(
        "SELECT id FROM actors WHERE id=%s", (created.invite["actor_id"],)
    ).fetchone()


@pytest.mark.parametrize("state", ["expired", "revoked"])
def test_reissue_keeps_actor_replaces_codes_and_refuses_replay(store, state):
    conn, observer, inviter, _ = store
    first = _create(store)
    column = "expires_at" if state == "expired" else "revoked_at"
    conn.execute(
        f"UPDATE teammate_invite_codes SET {column}=%s",
        (utc_now() - timedelta(seconds=1),),
    )
    conn.commit()
    before = _counts(observer)
    second = invites.reissue_invite(
        conn,
        invite_id=first.invite["invite_id"],
        actor_id=inviter,
        request_id="reissued",
    )
    assert second.invite["actor_id"] == first.invite["actor_id"]
    assert _counts(observer) == (before[0], before[1], before[2] + 1)
    assert invites.list_invites(conn, include_used=True) == [second.invite]
    _assert_refusal("invite_revoked", lambda: _redeem(conn, first.code), 410)
    _assert_refusal(
        "result_unavailable",
        lambda: invites.reissue_invite(
            conn,
            invite_id=first.invite["invite_id"],
            actor_id=inviter,
            request_id="reissued",
        ),
    )
    assert invites.list_invites(conn) == [second.invite]
    _redeem(conn, second.code)


def test_disabled_actor_wrong_machine_and_invalid_identity_leave_invite_pending(store):
    conn, _, inviter, _ = store
    created = _create(store)
    actor_id = created.invite["actor_id"]
    _assert_refusal(
        "invite_code_invalid", lambda: _redeem(conn, "yinv_" + "a" * 32), 404
    )
    _assert_refusal(
        "machine_identity_required", lambda: _redeem(conn, created.code, "bad"), 400
    )
    machine_id = str(uuid4())
    machine_credentials.register_with_credential(
        conn, machine_id=machine_id, name="Other", actor_id=inviter, now=utc_now()
    )
    _assert_refusal(
        "invite_machine_owned", lambda: _redeem(conn, created.code, machine_id), 409
    )
    conn.execute("UPDATE actors SET status='disabled' WHERE id=%s", (actor_id,))
    conn.commit()
    _assert_refusal("invite_actor_disabled", lambda: _redeem(conn, created.code), 403)
    _assert_refusal(
        "invite_reissue_disabled_actor",
        lambda: invites.reissue_invite(
            conn, invite_id=created.invite["invite_id"], actor_id=inviter
        ),
        409,
    )
    assert invites.list_invites(conn)[0]["state"] == "pending"


def test_registration_failure_rolls_back_consumption_machine_and_credential(
    store, monkeypatch
):
    conn, observer, _, _ = store
    created = _create(store)

    def fail(*args, **kwargs):
        raise RuntimeError("injected credential audit failure")

    with monkeypatch.context() as patch:
        patch.setattr(machine_credentials, "_audit", fail)
        with pytest.raises(RuntimeError, match="injected credential audit failure"):
            _redeem(conn, created.code)
    assert invites.list_invites(observer)[0]["state"] == "pending"
    assert observer.execute("SELECT count(*) FROM machines").fetchone() == (0,)
    assert observer.execute("SELECT count(*) FROM api_tokens").fetchone() == (0,)
    assert _redeem(conn, created.code)["token"]


def test_concurrent_redemption_returns_one_bound_credential(store):
    conn, observer, _, database = store
    created, barrier = _create(store), Barrier(2)

    def redeem():
        with pg_testdb.connect_test_database(database) as other:
            barrier.wait(timeout=10)
            try:
                return _redeem(other, created.code)
            except invites.TeammateInviteError as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: redeem(), range(2)))
    assert results.count("invite_consumed") == 1
    result = next(value for value in results if isinstance(value, dict))
    assert result["api_url"] == "https://team.example"
    assert result["org"] == conn.execute("SELECT slug FROM organizations").fetchone()[0]
    assert verify_token(conn, result["token"]).actor_id == created.invite["actor_id"]
    assert observer.execute("SELECT count(*) FROM api_tokens").fetchone() == (1,)
    assert observer.execute(
        "SELECT consumed_machine_id FROM teammate_invite_codes"
    ).fetchone()[0]


def test_boot_convergence_recreates_missing_table_and_preserves_issued_code(store):
    conn, _, _, _ = store
    conn.execute("DROP TABLE teammate_invite_codes")
    conn.commit()
    create_external_identity_tables(conn)
    created = _create(store)
    create_external_identity_tables(conn)
    assert invites.list_invites(conn) == [created.invite]
