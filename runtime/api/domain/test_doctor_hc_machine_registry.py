"""HC-machine-registry catches a machine id that changed, not only one missing."""

from __future__ import annotations

import pytest

from yoke_contracts.machine_config import machine_identity
from yoke_core.domain import machine_registry
from yoke_core.engines import doctor_hc_machine_registry as check
from yoke_core.engines.doctor_applicability import NOT_APPLICABLE
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from runtime.api.domain.machine_registry_test_support import (
    MACHINE_ID,
    NOW,
    registry_connection,
)


@pytest.fixture()
def local_machine(tmp_path, monkeypatch):
    """A host whose machine id and key resolve out of an isolated home."""
    monkeypatch.setattr(check, "_local_machine_id", lambda: MACHINE_ID)
    key = machine_identity.ensure_machine_keypair(tmp_path)
    monkeypatch.setattr(check, "_local_public_key", lambda: key)
    return key


def _run(conn) -> RecordCollector:
    rec = RecordCollector()
    check.hc_machine_registry(conn, DoctorArgs(), rec)
    return rec


def test_registered_machine_with_a_matching_key_passes(local_machine):
    conn = registry_connection()
    machine_registry.register_machine(
        conn,
        machine_id=MACHINE_ID,
        name="workshop-mac",
        actor_id=1,
        public_key=local_machine,
        now=NOW,
    )
    result = _run(conn).results[0]
    assert result.result == "PASS"
    assert "workshop-mac" in result.detail


def test_an_unregistered_machine_fails_with_the_registration_repair(local_machine):
    result = _run(registry_connection()).results[0]
    assert result.result == "FAIL"
    assert "yoke machine register" in result.detail


def test_a_changed_local_key_fails_where_a_missing_id_used_to_be_the_only_signal(
    local_machine, tmp_path
):
    conn = registry_connection()
    machine_registry.register_machine(
        conn,
        machine_id=MACHINE_ID,
        name="workshop-mac",
        actor_id=1,
        public_key=machine_identity.ensure_machine_keypair(tmp_path / "other"),
        now=NOW,
    )
    result = _run(conn).results[0]
    assert result.result == "FAIL"
    assert "different proof key" in result.detail
    assert "--rotate-key" in result.detail


def test_a_machine_with_no_id_yet_is_not_applicable(monkeypatch):
    monkeypatch.setattr(check, "_local_machine_id", lambda: "")
    result = _run(registry_connection()).results[0]
    assert result.result == NOT_APPLICABLE


def test_a_missing_local_key_fails(monkeypatch):
    monkeypatch.setattr(check, "_local_machine_id", lambda: MACHINE_ID)
    monkeypatch.setattr(check, "_local_public_key", lambda: "")
    result = _run(registry_connection()).results[0]
    assert result.result == "FAIL"
    assert "no local machine key" in result.detail
