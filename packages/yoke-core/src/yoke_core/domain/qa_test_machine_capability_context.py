"""Fleet readiness projection for the test-machine QA requirement kind."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.capabilities_list_read import (
    STATE_CONFIGURED_UNVERIFIED,
    STATE_ERROR,
    STATE_IN_USE,
    STATE_READY,
)
from yoke_core.domain.capabilities_test_machine_read import (
    read_test_machine_facts,
)
from yoke_core.domain.machine_qa_capability_rows import (
    test_machine_capability_rows,
)


def test_machine_capability_context(
    conn: Any,
    *,
    project_id: int,
) -> dict[str, Any]:
    """Return fleet availability while preserving per-machine serial limits."""
    rows = test_machine_capability_rows(conn, project_id=project_id)
    if not rows:
        return {"state": "not_configured"}
    verification, active_items, _method_count = read_test_machine_facts(
        conn,
        [project_id],
    )
    keys = [(project_id, row.capability_type) for row in rows]
    busy = [key for key in keys if key in active_items]
    free = [
        row for row in rows if (project_id, row.capability_type) not in active_items
    ]
    context: dict[str, Any] = {
        "state": STATE_CONFIGURED_UNVERIFIED,
        "concurrency_mode": "serial_per_machine",
        "machines_total": len(keys),
        "machines_in_use": len(busy),
    }
    if len(busy) == len(keys):
        context.update(
            {
                "state": STATE_IN_USE,
                "wait_reason": "all_machine_leases_in_use",
                "active_lease": {
                    "public_ref": next(
                        (active_items[key] for key in busy if active_items[key]),
                        None,
                    ),
                },
            }
        )
    elif any(
        verification.get(
            (project_id, row.capability_type), "verified" if row.verified_at else None
        )
        == "verified"
        for row in free
    ):
        context["state"] = STATE_READY
    elif free and all(
        verification.get((project_id, row.capability_type)) == STATE_ERROR
        for row in free
    ):
        context["state"] = STATE_ERROR
    return context


__all__ = ["test_machine_capability_context"]
