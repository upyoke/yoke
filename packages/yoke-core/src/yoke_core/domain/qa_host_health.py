"""Whether a physical Test Machine may take a scoped QA plan's next turn.

A failed owed reset requiring repair bars QA until a recovery reset succeeds
or a later fully passing governed verify reaches the owed baseline.
A failed verification independently bars QA until a successful ``verify`` or
``golden_capture``. Health is physical, like the one Test Machine queue.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.machine_qa_host_control import GOLDEN_CAPTURE_OPERATION
from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.machine_reset_debt import owed_reset, reset_command
from yoke_core.domain.schema_common import _table_exists

HOST_UNHEALTHY_REASON = "test_machine_host_unhealthy"
#: What a QA owner does when a Test Machine its cases need is taken or broken.
HOST_WAIT_TEACHING = (
    "If a Test Machine its cases need is busy or unhealthy, run the plan "
    "anyway: the runner queues this session in the Test Machine queue, then park; "
    "you are woken with the resume command when it is your turn. Write no "
    "host hold of your own."
)


def host_heal_commands(test_machine: str) -> str:
    """Repair readiness without replacing the machine's sealed baseline."""
    return f"`yoke test-machine verify --test-machine {test_machine}`"


def host_unhealthy(conn: Any, test_machine: str) -> dict[str, Any] | None:
    """Return the outstanding repair reset or failed verification, if any."""
    has_receipts = _table_exists(conn, "test_machine_operation_receipts")
    if has_receipts and (debt := owed_reset(conn, test_machine)) is not None:
        if (code := debt.repair_error_code) is not None:
            return {
                "test_machine": test_machine,
                "error_code": code,
                "reset_baseline": debt.baseline,
            }
    if not _table_exists(conn, "test_machine_verifications"):
        return None
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    facts = [
        (parse_instant(row["checked_at"]), str(row["status"]), row["error_code"])
        for row in query_rows(
            conn,
            "SELECT status,error_code,checked_at FROM test_machine_verifications "
            f"WHERE test_machine_id=(SELECT id FROM test_machines WHERE name={p}) AND checked_at IS NOT NULL",
            (test_machine,),
        )
    ]
    if has_receipts:
        facts += [
            (parse_instant(row["performed_at"]), "verified", None)
            for row in query_rows(
                conn,
                "SELECT performed_at FROM test_machine_operation_receipts "
                f"WHERE test_machine_id=(SELECT id FROM test_machines WHERE name={p}) AND operation={p} AND status='verified'",
                (test_machine, GOLDEN_CAPTURE_OPERATION),
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
    if baseline := health.get("reset_baseline"):
        name = health["test_machine"]
        return (
            f"{HOST_UNHEALTHY_REASON}: QA must wait to acquire {name}: "
            f"machine_needs_repair: its owed reset failed ({health['error_code']}). "
            f"The operator must repair that failure and run `{reset_command(name, baseline)}` "
            "to restore eligibility"
        )
    return (
        f"{HOST_UNHEALTHY_REASON}: QA must wait to acquire {health['test_machine']}: "
        f"its last verification failed ({health['error_code']} at "
        f"{health['checked_at']}). The operator must repair that failure and run "
        f"{host_heal_commands(health['test_machine'])}; successful verification wakes "
        "the queue. Keep the sealed baseline unchanged"
    )


__all__ = [
    "HOST_UNHEALTHY_REASON",
    "HOST_WAIT_TEACHING",
    "host_heal_commands",
    "host_unhealthy",
    "unhealthy_rationale",
]
