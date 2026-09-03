"""Machine identity: key material, signed proofs, and the reasons one fails."""

from __future__ import annotations

import base64
import json

import pytest

from yoke_contracts.machine_config import machine_identity


MACHINE_ID = "11111111-1111-4111-8111-111111111111"
NOW = "2026-09-03T12:00:00Z"


def test_keypair_is_created_once_and_kept_owner_only(tmp_path):
    first = machine_identity.ensure_machine_keypair(tmp_path)
    second = machine_identity.ensure_machine_keypair(tmp_path)
    assert first == second
    key_path = machine_identity.machine_key_path(tmp_path)
    assert key_path.stat().st_mode & 0o077 == 0
    assert len(base64.b64decode(first, validate=True)) == 32


def test_rotation_replaces_the_key(tmp_path):
    first = machine_identity.ensure_machine_keypair(tmp_path)
    rotated = machine_identity.ensure_machine_keypair(tmp_path, rotate=True)
    assert rotated != first
    assert machine_identity.machine_public_key(tmp_path) == rotated


def test_signed_proof_verifies_against_the_public_half(tmp_path):
    public_key = machine_identity.ensure_machine_keypair(tmp_path)
    proof = machine_identity.sign_machine_proof(
        MACHINE_ID, issued_at=NOW, home=tmp_path
    )
    machine_identity.verify_machine_proof(
        public_key=public_key,
        machine_id=MACHINE_ID,
        issued_at=proof.issued_at,
        signature=proof.signature,
        now=NOW,
    )


def test_proof_for_another_machine_id_does_not_verify(tmp_path):
    public_key = machine_identity.ensure_machine_keypair(tmp_path)
    proof = machine_identity.sign_machine_proof(
        MACHINE_ID, issued_at=NOW, home=tmp_path
    )
    with pytest.raises(machine_identity.MachineProofError) as excinfo:
        machine_identity.verify_machine_proof(
            public_key=public_key,
            machine_id="22222222-2222-4222-8222-222222222222",
            issued_at=proof.issued_at,
            signature=proof.signature,
            now=NOW,
        )
    assert excinfo.value.code == "machine_proof_invalid"


def test_a_second_host_key_does_not_verify_the_first_hosts_machine(tmp_path):
    """A copied machine id without the private key cannot produce a proof."""
    original = machine_identity.ensure_machine_keypair(tmp_path / "host-a")
    machine_identity.ensure_machine_keypair(tmp_path / "host-b")
    forged = machine_identity.sign_machine_proof(
        MACHINE_ID, issued_at=NOW, home=tmp_path / "host-b"
    )
    with pytest.raises(machine_identity.MachineProofError) as excinfo:
        machine_identity.verify_machine_proof(
            public_key=original,
            machine_id=MACHINE_ID,
            issued_at=forged.issued_at,
            signature=forged.signature,
            now=NOW,
        )
    assert excinfo.value.code == "machine_proof_invalid"


def test_stale_proof_is_refused_as_expired(tmp_path):
    public_key = machine_identity.ensure_machine_keypair(tmp_path)
    proof = machine_identity.sign_machine_proof(
        MACHINE_ID, issued_at="2026-09-03T11:00:00Z", home=tmp_path
    )
    with pytest.raises(machine_identity.MachineProofError) as excinfo:
        machine_identity.verify_machine_proof(
            public_key=public_key,
            machine_id=MACHINE_ID,
            issued_at=proof.issued_at,
            signature=proof.signature,
            now=NOW,
        )
    assert excinfo.value.code == "machine_proof_expired"
    assert "freshness window" in str(excinfo.value)


def test_signing_without_a_key_names_the_registration_recovery(tmp_path):
    with pytest.raises(machine_identity.MachineIdentityError) as excinfo:
        machine_identity.sign_machine_proof(MACHINE_ID, home=tmp_path)
    assert excinfo.value.code == "machine_key_missing"
    assert "yoke machine register" in str(excinfo.value)


def test_malformed_key_file_names_the_rotation_recovery(tmp_path):
    machine_identity.machine_key_path(tmp_path).write_text("{not json")
    with pytest.raises(machine_identity.MachineIdentityError) as excinfo:
        machine_identity.machine_public_key(tmp_path)
    assert excinfo.value.code == "machine_key_unreadable"
    assert "--rotate-key" in str(excinfo.value)


def test_key_document_records_its_algorithm(tmp_path):
    machine_identity.ensure_machine_keypair(tmp_path)
    document = json.loads(machine_identity.machine_key_path(tmp_path).read_text())
    assert document["algorithm"] == machine_identity.KEY_ALGORITHM
