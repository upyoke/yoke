"""Registering a machine, and the ways a second host is refused."""

from __future__ import annotations

import pytest

from yoke_contracts.machine_config import machine_access, machine_identity
from yoke_core.domain import machine_registry
from runtime.api.domain.machine_registry_test_support import (
    MACHINE_ID,
    NOW,
    registry_connection,
)


def _key(tmp_path, name: str = "host") -> str:
    return machine_identity.ensure_machine_keypair(tmp_path / name)


def test_registration_records_the_owner_and_the_public_half(tmp_path):
    conn = registry_connection()
    key = _key(tmp_path)
    record, created = machine_registry.register_machine(
        conn,
        machine_id=MACHINE_ID,
        name="workshop-mac",
        actor_id=1,
        public_key=key,
        now=NOW,
    )
    assert created is True
    assert record.name == "workshop-mac"
    assert record.owner_actor_id == 1
    assert record.proof_public_key == key
    assert record.access["use"]["mode"] == machine_access.USE_OWNER_ONLY


def test_re_registration_with_the_same_key_is_idempotent(tmp_path):
    conn = registry_connection()
    key = _key(tmp_path)
    machine_registry.register_machine(
        conn, machine_id=MACHINE_ID, name="a", actor_id=1, public_key=key, now=NOW
    )
    record, created = machine_registry.register_machine(
        conn, machine_id=MACHINE_ID, name="b", actor_id=1, public_key=key, now=NOW
    )
    assert created is False
    assert record.name == "b"


def test_a_different_key_on_a_known_id_is_refused_without_rotation(tmp_path):
    conn = registry_connection()
    machine_registry.register_machine(
        conn,
        machine_id=MACHINE_ID,
        name="a",
        actor_id=1,
        public_key=_key(tmp_path, "host-a"),
        now=NOW,
    )
    with pytest.raises(machine_registry.MachineRegistryError) as excinfo:
        machine_registry.register_machine(
            conn,
            machine_id=MACHINE_ID,
            name="a",
            actor_id=1,
            public_key=_key(tmp_path, "host-b"),
            now=NOW,
        )
    assert excinfo.value.code == "machine_proof_key_conflict"
    assert "--rotate-key" in str(excinfo.value)


def test_rotation_replaces_the_registered_key(tmp_path):
    conn = registry_connection()
    machine_registry.register_machine(
        conn,
        machine_id=MACHINE_ID,
        name="a",
        actor_id=1,
        public_key=_key(tmp_path, "host-a"),
        now=NOW,
    )
    rotated = _key(tmp_path, "host-b")
    record, _ = machine_registry.register_machine(
        conn,
        machine_id=MACHINE_ID,
        name="a",
        actor_id=1,
        public_key=rotated,
        rotate_key=True,
        now=NOW,
    )
    assert record.proof_public_key == rotated


def test_another_actor_cannot_take_over_a_registered_machine(tmp_path):
    conn = registry_connection()
    machine_registry.register_machine(
        conn,
        machine_id=MACHINE_ID,
        name="a",
        actor_id=1,
        public_key=_key(tmp_path),
        now=NOW,
    )
    with pytest.raises(machine_registry.MachineRegistryError) as excinfo:
        machine_registry.register_machine(
            conn,
            machine_id=MACHINE_ID,
            name="a",
            actor_id=2,
            public_key=_key(tmp_path, "host-b"),
            now=NOW,
        )
    assert excinfo.value.code == "machine_owner_mismatch"


def test_a_non_uuid_machine_id_is_refused(tmp_path):
    conn = registry_connection()
    with pytest.raises(machine_registry.MachineRegistryError) as excinfo:
        machine_registry.register_machine(
            conn,
            machine_id="machine-1",
            name="a",
            actor_id=1,
            public_key=_key(tmp_path),
            now=NOW,
        )
    assert excinfo.value.code == "machine_id_invalid"


def test_a_non_ed25519_public_key_is_refused(tmp_path):
    conn = registry_connection()
    with pytest.raises(machine_registry.MachineRegistryError) as excinfo:
        machine_registry.register_machine(
            conn,
            machine_id=MACHINE_ID,
            name="a",
            actor_id=1,
            public_key="c2hvcnQ=",
            now=NOW,
        )
    assert excinfo.value.code == "machine_public_key_invalid"


def test_requiring_an_unregistered_machine_names_the_recovery():
    conn = registry_connection()
    with pytest.raises(machine_registry.MachineRegistryError) as excinfo:
        machine_registry.require_machine(conn, MACHINE_ID)
    assert excinfo.value.code == "machine_unregistered"
    assert "yoke machine register" in str(excinfo.value)


def test_only_the_owner_or_an_administrator_may_change_access(tmp_path):
    conn = registry_connection()
    machine_registry.register_machine(
        conn,
        machine_id=MACHINE_ID,
        name="a",
        actor_id=1,
        public_key=_key(tmp_path),
        now=NOW,
    )
    universe = {"use": {"mode": machine_access.USE_UNIVERSE}}
    with pytest.raises(machine_registry.MachineRegistryError) as excinfo:
        machine_registry.set_machine_access(
            conn, machine_id=MACHINE_ID, access=universe, actor_id=2, now=NOW
        )
    assert excinfo.value.code == "machine_access_forbidden"
    owner_write = machine_registry.set_machine_access(
        conn, machine_id=MACHINE_ID, access=universe, actor_id=1, now=NOW
    )
    assert owner_write.access["use"]["mode"] == machine_access.USE_UNIVERSE
    admin_write = machine_registry.set_machine_access(
        conn,
        machine_id=MACHINE_ID,
        access={"use": {"mode": machine_access.USE_OWNER_ONLY}},
        actor_id=2,
        is_admin=True,
        now=NOW,
    )
    assert admin_write.access["use"]["mode"] == machine_access.USE_OWNER_ONLY


def test_an_incoherent_access_document_is_refused(tmp_path):
    conn = registry_connection()
    with pytest.raises(machine_registry.MachineRegistryError) as excinfo:
        machine_registry.register_machine(
            conn,
            machine_id=MACHINE_ID,
            name="a",
            actor_id=1,
            public_key=_key(tmp_path),
            access={"use": {"mode": machine_access.USE_ACTORS, "actor_ids": []}},
            now=NOW,
        )
    assert excinfo.value.code == "machine_access_invalid"
    assert machine_access.USE_SETTING in str(excinfo.value)


def test_registered_names_render_for_report_readers(tmp_path):
    conn = registry_connection()
    machine_registry.register_machine(
        conn,
        machine_id=MACHINE_ID,
        name="workshop-mac",
        actor_id=1,
        public_key=_key(tmp_path),
        now=NOW,
    )
    names = machine_registry.machine_names(conn)
    assert names == {MACHINE_ID: "workshop-mac"}
    assert machine_registry.display_name(names, MACHINE_ID) == "workshop-mac"
    assert machine_registry.display_name(names, "unknown") == "unknown"
