"""HC-machine-registry catches an unregistered machine before a launch does."""

from __future__ import annotations

import pytest

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
def local_machine(monkeypatch):
    """A host whose machine id resolves without reading the real config."""
    monkeypatch.setattr(check, "_local_machine_id", lambda: MACHINE_ID)
    return MACHINE_ID


def _run(conn) -> RecordCollector:
    rec = RecordCollector()
    check.hc_machine_registry(conn, DoctorArgs(), rec)
    return rec


def test_a_registered_machine_passes_and_names_itself(local_machine):
    conn = registry_connection()
    machine_registry.register_machine(
        conn,
        machine_id=MACHINE_ID,
        name="workshop-mac",
        actor_id=1,
        now=NOW,
    )
    result = _run(conn).results[0]
    assert result.result == "PASS"
    assert "workshop-mac" in result.detail


def test_an_unregistered_machine_fails_with_the_registration_repair(local_machine):
    result = _run(registry_connection()).results[0]
    assert result.result == "FAIL"
    assert "yoke machine register" in result.detail


def test_a_machine_with_no_id_yet_is_not_applicable(monkeypatch):
    monkeypatch.setattr(check, "_local_machine_id", lambda: "")
    result = _run(registry_connection()).results[0]
    assert result.result == NOT_APPLICABLE
