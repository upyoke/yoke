from __future__ import annotations

import pytest

from yoke_contracts.machine_config.test_machine import TestMachineCapabilityError
from yoke_contracts.machine_qa_execution import (
    VERIFICATION_BASELINES,
    VERIFICATION_CHECKS,
)
from yoke_core.domain.capabilities_test_machine_read import read_test_machine_facts
from yoke_core.domain.machine_qa_capability import (
    host_claim_key,
    host_claim_target,
    replace_test_machine_settings,
    test_machine_detail as read_test_machine_detail,
)
from yoke_core.domain.machine_qa_execution_protocol import (
    MachineQaProtocolLeaseHeld,
    begin_host_control_execution,
)

from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.machine_qa_test_support import (
    make_conn,
    register_test_machine,
)


SHARED_HOST = "mac-mini-lab"


def _settings(resource_name: str = SHARED_HOST) -> dict[str, str]:
    return {
        "resource_name": resource_name,
        "host": "test-mac.local",
        "user": "yoke-test",
        "operating_notes": "Do not interrupt an active lease.",
    }


def _two_project_conn():
    conn = make_conn()
    conn.execute(
        "INSERT INTO projects(id,slug,name,public_item_prefix) "
        "VALUES(2,'buzz','Buzz','BUZ')"
    )
    return conn


def _shared_host_conn():
    conn = _two_project_conn()
    # A second project naming one host is what the registration guard
    # refuses; seeding it directly proves one physical machine still
    # admits one execution.
    register_test_machine(conn, project_id=1, created_at="2026-08-01T00:00:00Z")
    register_test_machine(conn, project_id=2, created_at="2026-08-02T00:00:00Z")
    return conn


def _begin_verification(conn, *, project: str, session_id: str, actor_id: str):
    seed_qa_session(conn, session_id, actor_id=int(actor_id))
    return begin_host_control_execution(
        conn,
        project=project,
        session_id=session_id,
        operation="verify",
        checks=VERIFICATION_CHECKS,
        baselines=VERIFICATION_BASELINES,
    )


def test_registering_a_host_a_second_project_already_operates_is_refused() -> None:
    conn = _two_project_conn()
    replace_test_machine_settings(
        conn,
        project="yoke",
        settings=_settings(),
        base_settings=None,
    )

    with pytest.raises(TestMachineCapabilityError) as caught:
        replace_test_machine_settings(
            conn,
            project="buzz",
            settings=_settings(),
            base_settings=None,
        )

    assert "already registered by project 'yoke'" in str(caught.value)
    replace_test_machine_settings(
        conn,
        project="buzz",
        settings=_settings("mac-studio-lab"),
        base_settings=None,
    )
    assert host_claim_target("mac-studio-lab").machine_id == "mac-studio-lab"


def test_re_saving_settings_for_an_own_host_is_not_a_duplicate_registration() -> None:
    conn = _two_project_conn()
    first = replace_test_machine_settings(
        conn,
        project="yoke",
        settings=_settings(),
        base_settings=None,
    )

    second = replace_test_machine_settings(
        conn,
        project="yoke",
        settings={**_settings(), "operating_notes": "Lab moved to rack two."},
        base_settings=first["settings_token"],
    )

    assert second["settings"]["operating_notes"] == "Lab moved to rack two."


def test_a_shared_host_is_one_claim_whichever_project_drives_it() -> None:
    """The machine alone is the scope, so no project anchor is needed."""
    conn = _shared_host_conn()

    contract = _begin_verification(
        conn,
        project="buzz",
        session_id="buzz-session",
        actor_id="3",
    )

    assert contract.project == "buzz"
    assert contract.lease_key == host_claim_key(SHARED_HOST)
    row = conn.execute(
        "SELECT target_kind,scope FROM work_claims WHERE id=?",
        (contract.lease_id,),
    ).fetchone()
    assert str(row[0]) == "qa_admission"
    assert str(row[1]) == host_claim_target(SHARED_HOST).scope_json()


def test_one_physical_host_admits_one_execution_across_every_project() -> None:
    conn = _shared_host_conn()
    _begin_verification(conn, project="yoke", session_id="yoke-session", actor_id="2")

    with pytest.raises(MachineQaProtocolLeaseHeld) as from_other_project:
        _begin_verification(
            conn,
            project="buzz",
            session_id="buzz-session",
            actor_id="3",
        )
    with pytest.raises(MachineQaProtocolLeaseHeld) as from_same_project:
        _begin_verification(
            conn,
            project="yoke",
            session_id="second-yoke-session",
            actor_id="4",
        )

    for caught in (from_other_project, from_same_project):
        assert caught.value.machine == SHARED_HOST
        assert caught.value.lease.session_id == "yoke-session"
        assert caught.value.lease.project_id == 1


def test_a_leased_shared_host_reads_as_in_use_for_every_naming_project() -> None:
    conn = _shared_host_conn()
    _begin_verification(conn, project="yoke", session_id="yoke-session", actor_id="2")

    _verification, active_items, _method_count = read_test_machine_facts(conn, [1, 2])

    assert set(active_items) == {1, 2}
    detail = read_test_machine_detail(conn, project="buzz")
    assert detail["active_lease"]["session_id"] == "yoke-session"
