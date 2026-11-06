# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.api_hooks_evaluate_route_test_support import client as client
from runtime.api.api_hooks_evaluate_route_test_support import hooks_db as hooks_db

import json

from uuid import uuid4

import pytest

from runtime.api.api_items_test_helpers import (
    _client_for_db,
    make_test_db_fixture,
)

from runtime.api.api_hooks_evaluate_route_test_support import _request_body

from yoke_core.domain import db_helpers


def _stored_session(session):
    with db_helpers.connect() as conn:
        row = conn.execute(
            "SELECT * FROM harness_sessions WHERE session_id=%s", (session,)
        ).fetchone()
        return dict(row) if row is not None else None


def _machine_request(session, machine, workspace, **extra):
    return _request_body(
        event_name="SessionStart",
        project_id=None,
        machine_id=machine,
        stdin=json.dumps(
            {"session_id": session, "identity_stamped": True, "cwd": str(workspace)}
        ),
        **extra,
    )


@pytest.fixture()
def machine_client(client):
    from yoke_core.domain import api_tokens, machine_credentials
    from yoke_contracts.timestamps import utc_now

    with db_helpers.connect() as conn:
        account = api_tokens.verify_token(
            conn, client.headers["authorization"].split(" ", 1)[1]
        )
        machine = str(uuid4())
        credential = machine_credentials.register_with_credential(
            conn,
            machine_id=machine,
            name="hook-client",
            actor_id=account.actor_id,
            now=utc_now(),
        )[2]
        verified = api_tokens.verify_token(conn, credential.token)
        assert (verified.actor_id, verified.machine_id) == (account.actor_id, machine)
    client.headers["authorization"] = f"Bearer {credential.token}"
    return client, account.actor_id, machine
