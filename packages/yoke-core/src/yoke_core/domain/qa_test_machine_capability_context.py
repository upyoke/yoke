"""Universe Test Machine readiness for QA capability requirements."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.coordination_claims import active_claim
from yoke_core.domain.machine_qa_capability import _holder_item, host_claim_target
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.test_machine_rows import test_machine_rows


def test_machine_capability_context(
    conn: Any, *, test_machine: str | None = None
) -> dict[str, Any]:
    """Report readiness of all Test Machines or the specifically required host."""
    if not _table_exists(conn, "test_machines"):
        return {"state": "not_configured"}
    machines = [
        machine for machine in test_machine_rows(conn)
        if test_machine is None or machine.test_machine == test_machine
    ]
    if not machines:
        return {"state": "not_configured"}

    verifications = dict(
        conn.execute("SELECT test_machine_id, status FROM test_machine_verifications").fetchall()
    )
    leases = {
        machine.id: active_claim(conn, host_claim_target(machine.test_machine))
        for machine in machines
    }
    busy = sum(lease is not None for lease in leases.values())
    context = {
        "state": "configured_unverified",
        "concurrency_mode": "serial_per_machine",
        "machines_total": len(machines),
        "oses": sorted({machine.settings["os"] for machine in machines}),
        "machines_in_use": busy,
    }
    if busy == len(machines):
        refs = (
            _holder_item(conn, session_id=lease.session_id)
            for lease in leases.values() if lease is not None
        )
        context.update(
            state="in_use",
            wait_reason="all_machine_leases_in_use",
            active_lease={"public_ref": next((item["ref"] for item in refs if item), None)},
        )
    else:
        statuses = [
            verifications.get(machine.id, "verified" if machine.verified_at else None)
            for machine in machines if leases[machine.id] is None
        ]
        if "verified" in statuses:
            context["state"] = "ready"
        elif all(status == "error" for status in statuses):
            context["state"] = "error"
    return context
