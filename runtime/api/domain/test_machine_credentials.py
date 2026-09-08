"""Machine-bound bearer rotation and retirement preserve account access."""

from __future__ import annotations

import pytest

from runtime.api.domain.machine_registry_test_support import (
    MACHINE_ID,
    NOW,
    registry_connection,
)
from yoke_core.domain import api_tokens, machine_credentials, machine_registry


def _connection():
    conn = registry_connection()
    conn.executescript(
        """
        CREATE TABLE api_tokens (
            id INTEGER PRIMARY KEY,
            token_hash TEXT NOT NULL UNIQUE,
            actor_id INTEGER NOT NULL,
            machine_id TEXT,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            revoked_at TEXT,
            expires_at TEXT,
            last_used_at TEXT,
            diagnostic_metadata TEXT
        );
        CREATE TABLE api_token_audit (
            id INTEGER PRIMARY KEY,
            api_token_id INTEGER,
            actor_id INTEGER,
            project_id INTEGER,
            event_type TEXT NOT NULL,
            outcome TEXT NOT NULL,
            permission_key TEXT,
            diagnostic_metadata TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    return conn


def test_registration_returns_one_machine_bearer_and_rotation_revokes_the_old_one():
    conn = _connection()
    first = machine_credentials.register_with_credential(
        conn, machine_id=MACHINE_ID, name="workshop", actor_id=1, now=NOW
    )[2]
    second = machine_credentials.register_with_credential(
        conn, machine_id=MACHINE_ID, name="workshop", actor_id=1, now=NOW
    )[2]

    assert first.token != second.token
    with pytest.raises(api_tokens.TokenRevoked):
        api_tokens.verify_token(conn, first.token)
    verified = api_tokens.verify_token(conn, second.token)
    assert verified.machine_id == MACHINE_ID
    assert verified.actor_id == 1


def test_retirement_revokes_only_bound_credentials_and_refuses_same_identity():
    conn = _connection()
    account = api_tokens.mint_token(conn, actor_id=1, name="account")
    credential = machine_credentials.register_with_credential(
        conn, machine_id=MACHINE_ID, name="workshop", actor_id=1, now=NOW
    )[2]

    retired = machine_credentials.retire_with_credentials(
        conn, machine_id=MACHINE_ID, actor_id=1, now=NOW
    )

    assert retired.retired_at == NOW
    with pytest.raises(api_tokens.TokenMachineRetired):
        api_tokens.verify_token(conn, credential.token)
    audit = conn.execute(
        "SELECT outcome FROM api_token_audit WHERE api_token_id=? "
        "ORDER BY id DESC LIMIT 1",
        (credential.token_id,),
    ).fetchone()
    assert audit[0] == "machine_retired"
    assert api_tokens.verify_token(conn, account.raw_token).machine_id is None
    with pytest.raises(machine_registry.MachineRegistryError) as excinfo:
        machine_credentials.register_with_credential(
            conn, machine_id=MACHINE_ID, name="workshop", actor_id=1, now=NOW
        )
    assert excinfo.value.code == "machine_retired"
    with pytest.raises(machine_registry.MachineRegistryError) as access_error:
        machine_registry.set_machine_access(
            conn,
            machine_id=MACHINE_ID,
            access={"use": {"mode": "universe"}},
            actor_id=1,
            now=NOW,
        )
    assert access_error.value.code == "machine_retired"


def test_another_actor_cannot_retire_the_machine():
    conn = _connection()
    machine_credentials.register_with_credential(
        conn, machine_id=MACHINE_ID, name="workshop", actor_id=1, now=NOW
    )
    with pytest.raises(machine_registry.MachineRegistryError) as excinfo:
        machine_credentials.retire_with_credentials(
            conn, machine_id=MACHINE_ID, actor_id=2, now=NOW
        )
    assert excinfo.value.code == "machine_retire_forbidden"
