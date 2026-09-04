"""Approving a machine admits it; it never hands the approver the machine."""

from __future__ import annotations

import pytest

from runtime.api.domain.decision_request_test_support import (
    decision_request_connection,
)
from runtime.api.domain.machine_registry_test_support import MACHINE_ID, NOW
from yoke_core.domain import machine_approval_requests as approvals
from yoke_core.domain import machine_registry
from yoke_core.domain.decision_request_resolution import resolve_decision_request
from yoke_core.domain.machine_registry_schema import (
    ensure_machine_registry_schema,
)


AUTH_REQUEST_ID = "5b234860-c927-46ab-b19a-9fb36df056aa"
INSTALLER = 1
ORG_ADMIN = 5


@pytest.fixture()
def conn():
    with decision_request_connection() as value:
        ensure_machine_registry_schema(value)
        yield value


def test_approving_for_another_actor_leaves_the_machine_with_its_installer(
    conn,
) -> None:
    """The owner is whoever installed Yoke there, not whoever said yes.

    An org admin answers a machine gate for other people all day. If
    approving made the approver the owner, the person at that machine would
    be locked out of their own registration the moment someone else helped
    them in.
    """
    pending = approvals.apply_machine_approval_lifecycle(
        conn,
        auth_request_id=AUTH_REQUEST_ID,
        org_id=1,
        state="pending",
        occurred_at="2026-09-04T12:00:00Z",
        actor_id=INSTALLER,
        context={
            "expires_at": "2026-09-04T12:10:00Z",
            "code": "WXYZ-1234",
            "machine": "studio-mini",
        },
    )[0]
    assert pending["originator_actor_id"] == INSTALLER

    resolved = resolve_decision_request(
        conn,
        int(pending["id"]),
        actor_id=ORG_ADMIN,
        action="approve",
        session_id="workbench",
    )
    assert resolved["resolution_action"] == "approve"

    record, created = machine_registry.register_machine(
        conn,
        machine_id=MACHINE_ID,
        name="studio-mini",
        actor_id=INSTALLER,
        now=NOW,
    )
    assert (created, record.owner_actor_id) == (True, INSTALLER)

    with pytest.raises(machine_registry.MachineRegistryError) as excinfo:
        machine_registry.register_machine(
            conn,
            machine_id=MACHINE_ID,
            name="studio-mini",
            actor_id=ORG_ADMIN,
            now=NOW,
        )
    assert excinfo.value.code == "machine_owner_mismatch"
