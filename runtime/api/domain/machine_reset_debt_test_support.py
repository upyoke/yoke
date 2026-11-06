# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from types import SimpleNamespace

import pytest

from runtime.api.domain import (
    agent_mission_cleanup_test_support as cleanup_support,
)

from runtime.api.domain.machine_operation_test_support import run_operation

from yoke_core.domain.agent_mission_recording import handle_agent_mission_access

from yoke_core.domain.coordination_claims import get_claim

from yoke_core.domain.machine_reset_debt import record_reset_owed, reset_owed

from yoke_core.domain.qa_plan_execution_state import lock_plan_execution


def _debt(conn, baseline="fresh-host"):
    from runtime.api.domain.machine_operation_test_support import MACHINE

    record_reset_owed(
        conn,
        case={"project_id": 1, "host_baseline": baseline},
        test_machine=MACHINE,
        lease_id=77,
    )
    conn.commit()
    return MACHINE


def verified_reset(conn, test_machine, baseline, project_id=1):
    from yoke_core.domain.machine_operation_recording import (
        record_test_machine_operation,
    )

    record_test_machine_operation(
        conn,
        project_id,
        test_machine=test_machine,
        operation="reset",
        status="verified",
        checks=[{"name": baseline, "ok": True}],
        error_code=None,
        lease_id=76,
        contract_digest="",
    )
