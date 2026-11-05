# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

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


def _assert_refusal(code, operation, status=None):
    with pytest.raises(invites.TeammateInviteError) as caught:
        operation()
    assert caught.value.code == code
    assert str(caught.value)
    if status:
        assert caught.value.status == status
