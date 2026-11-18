"""The session holding a Test Machine's lease may change its settings; others wait."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_config.test_machine import TestMachineCapabilityError
from yoke_core.domain.machine_qa_capability import replace_test_machine_settings

from runtime.api.domain.machine_qa_test_support import make_conn

SETTINGS = {
    "resource_name": "mac-mini-lab",
    "host": "test-mac.local",
    "user": "yoke-test",
    "os": "macos",
    "operating_notes": "",
}


def _leased_by(session_id):
    conn = make_conn()
    replace_test_machine_settings(
        conn, power_project="yoke", settings=SETTINGS, base_settings=None
    )
    conn.execute(
        "INSERT INTO harness_sessions(session_id,actor_id) VALUES(?,2)", (session_id,)
    )
    conn.execute(
        "INSERT INTO work_claims(id,session_id,target_kind,scope,claimed_at,"
        "last_heartbeat,released_at) VALUES(9,?,'qa_admission',"
        "'{\"test_machine\":\"mac-mini-lab\"}','2026-07-26T15:58:00Z',"
        "'2026-07-26T15:59:00Z',NULL)",
        (session_id,),
    )
    conn.commit()
    base = conn.execute(
        "SELECT settings FROM test_machines WHERE name='mac-mini-lab'"
    ).fetchone()[0]
    return conn, base


def _replace(conn, base, caller):
    return replace_test_machine_settings(
        conn,
        settings={**SETTINGS, "operating_notes": "changed by the lease holder"},
        base_settings=base,
        caller_session_id=caller,
    )


def test_lease_holder_replaces_its_own_machine_settings():
    conn, base = _leased_by("holder")
    _replace(conn, base, "holder")
    stored = conn.execute(
        "SELECT settings FROM test_machines WHERE name='mac-mini-lab'"
    ).fetchone()[0]
    assert json.loads(stored)["operating_notes"] == "changed by the lease holder"


@pytest.mark.parametrize("caller", ["someone-else", None])
def test_another_session_or_unknown_caller_is_refused_naming_the_holder(caller):
    conn, base = _leased_by("holder")
    with pytest.raises(TestMachineCapabilityError, match="leased by session holder"):
        _replace(conn, base, caller)
    stored = conn.execute(
        "SELECT settings FROM test_machines WHERE name='mac-mini-lab'"
    ).fetchone()[0]
    assert stored == base


def test_handler_passes_the_calling_session(monkeypatch):
    from yoke_core.domain.handlers import machine_qa as handler

    seen = {}

    def replace(conn, **kwargs):
        seen.update(kwargs)
        return {}

    monkeypatch.setattr(handler, "replace_test_machine_settings", replace)
    monkeypatch.setattr(
        handler.db_helpers, "connect", lambda: SimpleNamespace(close=lambda: None)
    )
    request = SimpleNamespace(
        actor=SimpleNamespace(session_id="holder"),
        payload={"settings": SETTINGS, "base_settings": "{}"},
    )
    assert handler.handle_settings_replace(request).primary_success
    assert seen["caller_session_id"] == "holder"
