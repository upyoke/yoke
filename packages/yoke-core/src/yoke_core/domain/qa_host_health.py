"""Whether a physical Test Machine may take a scoped QA plan's next turn.

A host is unhealthy while its newest health fact is a failed verification:
the readiness row every availability surface reads. A later successful
``verify`` or ``golden_capture`` heals it. Reset and diagnosis receipts record
what was last done to the machine, not whether it works, so they never
decide admission. Health is physical: every project registering the machine
contributes its facts, like the one waiting line the machine keeps.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.machine_config.test_machine import test_machine_capability_type
from yoke_contracts.machine_qa_host_control import GOLDEN_CAPTURE_OPERATION
from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.schema_common import _table_exists

HOST_UNHEALTHY_REASON = "test_machine_host_unhealthy"
#: What a QA owner does when a Test Machine its cases need is taken or broken.
HOST_WAIT_TEACHING = (
    "If a Test Machine its cases need is busy or unhealthy, run the plan "
    "anyway: the runner queues this session in that host's line, then park; "
    "you are woken with the resume command when it is your turn. Write no "
    "host hold of your own."
)


def host_heal_commands(test_machine: str) -> str:
    """Repair readiness without replacing the machine's sealed baseline."""
    return f"`yoke test-machine verify --test-machine {test_machine} --project PROJECT`"


def host_unhealthy(conn: Any, test_machine: str) -> dict[str, Any] | None:
    """Return the failed verification that still bars *machine*, else None."""
    if not _table_exists(conn, "test_machine_verifications"):
        return None
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    capability = test_machine_capability_type(test_machine)
    facts = [
        (parse_instant(row["checked_at"]), str(row["status"]), row["error_code"])
        for row in query_rows(
            conn,
            "SELECT status,error_code,checked_at FROM test_machine_verifications "
            f"WHERE capability_type={p} AND checked_at IS NOT NULL",
            (capability,),
        )
    ]
    if _table_exists(conn, "test_machine_operation_receipts"):
        facts += [
            (parse_instant(row["performed_at"]), "verified", None)
            for row in query_rows(
                conn,
                "SELECT performed_at FROM test_machine_operation_receipts "
                f"WHERE capability_type={p} AND operation={p} AND status='verified'",
                (capability, GOLDEN_CAPTURE_OPERATION),
            )
        ]
    if not facts:
        return None
    checked_at, status, error_code = max(facts, key=lambda fact: fact[0])
    if status != "error":
        return None
    return {
        "test_machine": test_machine,
        "error_code": str(error_code or "unknown"),
        "checked_at": format_instant(checked_at),
    }


def unhealthy_rationale(health: dict[str, Any]) -> str:
    """One sentence naming the failure and the operation that heals it."""
    return (
        f"{HOST_UNHEALTHY_REASON}: QA must wait to acquire {health['test_machine']}: "
        f"its last verification failed ({health['error_code']} at "
        f"{health['checked_at']}). The operator must repair that failure and run "
        f"{host_heal_commands(health['test_machine'])}; successful verification wakes "
        "the host line. Keep the sealed baseline unchanged"
    )


__all__ = [
    "HOST_UNHEALTHY_REASON",
    "HOST_WAIT_TEACHING",
    "host_heal_commands",
    "host_unhealthy",
    "unhealthy_rationale",
]
