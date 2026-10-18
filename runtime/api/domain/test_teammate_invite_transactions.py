"""Atomic teammate creation, rollback visibility and concurrent replay."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from yoke_core.domain import teammate_invite_codes as invites
from yoke_core.domain.actor_role_grants import grant_actor_org_role
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.external_identities import default_org_id

from runtime.api.domain.test_teammate_invite_codes import (
    _assert_refusal,
    _counts,
    _create,
)
from runtime.api.domain.test_teammate_invite_codes import store as store
from runtime.api.fixtures import pg_testdb


def test_atomic_create_hash_expiry_role_and_names(store):
    conn, observer, inviter, _ = store
    before = _counts(observer)
    created = _create(store)
    assert _counts(observer) == tuple(n + 1 for n in before)
    assert invites.parse_invite_code(created.code) == created.code
    assert len(created.code) == 37
    assert created.code not in repr(created)
    stored = observer.execute(
        "SELECT code_hash,created_at,expires_at,invited_by_actor_id "
        "FROM teammate_invite_codes WHERE id=%s",
        (created.invite["invite_id"],),
    ).fetchone()
    assert stored[0] == invites._hash(created.code) and created.code not in stored
    assert stored[2] - stored[1] == timedelta(seconds=86400)
    assert stored[3] == inviter
    assert created.invite["role"] == "operator"
    role = observer.execute(
        "SELECT r.name FROM actor_org_roles g JOIN roles r ON r.id=g.role_id "
        "WHERE g.actor_id=%s",
        (created.invite["actor_id"],),
    ).fetchone()
    assert role == ("operator",)
    again = _create(store)
    assert again.invite["actor_id"] != created.invite["actor_id"]
    assert observer.execute("SELECT count(*) FROM actor_invites").fetchone() == (0,)
    assert observer.execute("SELECT count(*) FROM api_tokens").fetchone() == (0,)


@pytest.mark.parametrize("step", ["grant_actor_org_role", "_issue"])
def test_failure_after_each_creation_helper_rolls_back_every_row(
    store, monkeypatch, step
):
    conn, observer, _, _ = store
    before = _counts(observer)

    def fail(*args, **kwargs):
        assert _counts(conn) == (
            before[0] + 1,
            before[1] + (step == "_issue"),
            before[2],
        )
        raise RuntimeError("injected creation failure")

    monkeypatch.setattr(invites, step, fail)
    with pytest.raises(RuntimeError, match="injected creation failure"):
        _create(store)
    assert _counts(observer) == before


def test_default_commit_helpers_are_visible_from_another_connection(store):
    conn, observer, _, _ = store
    actor_id = seed_human_actor(conn, "Default commit")
    assert observer.execute(
        "SELECT name FROM actors WHERE id=%s", (actor_id,)
    ).fetchone()
    grant_actor_org_role(
        conn, actor_id=actor_id, org_id=default_org_id(conn), role_name="operator"
    )
    assert observer.execute(
        "SELECT r.name FROM actor_org_roles g JOIN roles r ON r.id=g.role_id "
        "WHERE g.actor_id=%s",
        (actor_id,),
    ).fetchone() == ("operator",)


def test_replay_creates_nothing_and_other_integrity_failures_are_not_replays(store):
    conn, observer, _, _ = store
    _create(store, request_id="one-result")
    before = _counts(observer)
    _assert_refusal(
        "result_unavailable", lambda: _create(store, request_id="one-result")
    )
    with pytest.raises(invites.db_backend.integrity_error_types(conn)):
        invites.create_invite(
            conn,
            name="Invalid inviter",
            inviter_actor_id=-1,
            request_id="invalid-inviter",
        )
    assert _counts(observer) == before


def test_concurrent_create_same_request_commits_only_one_actor(store, monkeypatch):
    _, observer, inviter, database = store
    before, barrier = _counts(observer), Barrier(2)
    request_used = invites._request_used

    def check(conn, request_id):
        used = request_used(conn, request_id)
        if not used:
            barrier.wait(timeout=10)
        return used

    monkeypatch.setattr(invites, "_request_used", check)

    def create():
        with pg_testdb.connect_test_database(database) as conn:
            try:
                return invites.create_invite(
                    conn,
                    name="Concurrent",
                    inviter_actor_id=inviter,
                    request_id="concurrent",
                ).invite["state"]
            except invites.TeammateInviteError as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: create(), range(2))) == [
            "pending",
            "result_unavailable",
        ]
    assert _counts(observer) == tuple(n + 1 for n in before)
