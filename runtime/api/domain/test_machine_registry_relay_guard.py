"""The relay identity gate: an unproved poll never becomes a live relay."""

from __future__ import annotations

import pytest

from yoke_contracts.machine_config import machine_identity
from yoke_core.domain import machine_registry
from yoke_core.domain.machine_registry_relay_guard import require_proved_machine
from runtime.api.domain.machine_registry_test_support import (
    MACHINE_ID,
    NOW,
    registry_connection,
)


def _registered(conn, tmp_path, *, actor_id: int = 1, home: str = "host-a") -> str:
    key = machine_identity.ensure_machine_keypair(tmp_path / home)
    machine_registry.register_machine(
        conn,
        machine_id=MACHINE_ID,
        name="workshop-mac",
        actor_id=actor_id,
        public_key=key,
        now=NOW,
    )
    return key


def _proof(tmp_path, home: str = "host-a", issued_at: str = NOW):
    return machine_identity.sign_machine_proof(
        MACHINE_ID, issued_at=issued_at, home=tmp_path / home
    )


def test_a_proved_poll_passes_and_stamps_liveness(tmp_path):
    conn = registry_connection()
    _registered(conn, tmp_path)
    proof = _proof(tmp_path)
    record = require_proved_machine(
        conn,
        machine_id=MACHINE_ID,
        actor_id=1,
        proof_issued_at=proof.issued_at,
        proof_signature=proof.signature,
        now=NOW,
    )
    assert record.name == "workshop-mac"
    assert machine_registry.require_machine(conn, MACHINE_ID).last_seen_at == NOW


def test_an_unregistered_machine_is_refused_by_name(tmp_path):
    conn = registry_connection()
    machine_identity.ensure_machine_keypair(tmp_path / "host-a")
    proof = _proof(tmp_path)
    with pytest.raises(machine_registry.MachineRegistryError) as excinfo:
        require_proved_machine(
            conn,
            machine_id=MACHINE_ID,
            actor_id=1,
            proof_issued_at=proof.issued_at,
            proof_signature=proof.signature,
            now=NOW,
        )
    assert excinfo.value.code == "machine_unregistered"
    assert "yoke machine register" in str(excinfo.value)


def test_a_poll_carrying_no_proof_is_refused_by_name(tmp_path):
    conn = registry_connection()
    _registered(conn, tmp_path)
    with pytest.raises(machine_registry.MachineRegistryError) as excinfo:
        require_proved_machine(
            conn,
            machine_id=MACHINE_ID,
            actor_id=1,
            proof_issued_at="",
            proof_signature="",
            now=NOW,
        )
    assert excinfo.value.code == "machine_proof_missing"
    assert "yoke machine register" in str(excinfo.value)


def test_a_copied_machine_id_without_the_key_is_refused(tmp_path):
    """The second box mints its own key; its proof does not match the row."""
    conn = registry_connection()
    _registered(conn, tmp_path, home="host-a")
    machine_identity.ensure_machine_keypair(tmp_path / "host-b")
    forged = _proof(tmp_path, home="host-b")
    with pytest.raises(machine_registry.MachineRegistryError) as excinfo:
        require_proved_machine(
            conn,
            machine_id=MACHINE_ID,
            actor_id=1,
            proof_issued_at=forged.issued_at,
            proof_signature=forged.signature,
            now=NOW,
        )
    assert excinfo.value.code == "machine_proof_invalid"
    assert "--rotate-key" in str(excinfo.value)


def test_a_relay_polling_as_another_actors_machine_is_refused(tmp_path):
    conn = registry_connection()
    _registered(conn, tmp_path, actor_id=1)
    proof = _proof(tmp_path)
    with pytest.raises(machine_registry.MachineRegistryError) as excinfo:
        require_proved_machine(
            conn,
            machine_id=MACHINE_ID,
            actor_id=2,
            proof_issued_at=proof.issued_at,
            proof_signature=proof.signature,
            now=NOW,
        )
    assert excinfo.value.code == "machine_owner_mismatch"


def test_a_stale_proof_is_refused_as_expired(tmp_path):
    conn = registry_connection()
    _registered(conn, tmp_path)
    proof = _proof(tmp_path, issued_at="2026-09-03T10:00:00Z")
    with pytest.raises(machine_registry.MachineRegistryError) as excinfo:
        require_proved_machine(
            conn,
            machine_id=MACHINE_ID,
            actor_id=1,
            proof_issued_at=proof.issued_at,
            proof_signature=proof.signature,
            now=NOW,
        )
    assert excinfo.value.code == "machine_proof_expired"
