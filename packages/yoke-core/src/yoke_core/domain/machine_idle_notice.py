"""Notify the releasing client of pending work on free Test Machines."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_released: ContextVar[set[str] | None] = ContextVar(
    "released_test_machines", default=None
)


@contextmanager
def collect_released_hosts() -> Iterator[set[str]]:
    """Collect the hosts released free while one function call runs."""
    hosts: set[str] = set()
    token = _released.set(hosts)
    try:
        yield hosts
    finally:
        _released.reset(token)


def note_released_host(conn: Any, target: Any) -> None:
    """Record a released host unless a waiter's turn now holds it."""
    hosts = _released.get()
    if hosts is None:
        return
    from yoke_core.domain.coordination_claims import active_claim

    if active_claim(conn, target) is not None:
        return
    hosts.add(str(target.test_machine))


def released_cloud_machines(hosts: set[str]) -> list[dict[str, str]]:
    """The released hosts that record ``cloud_instance_id``, by project."""
    if not hosts:
        return []
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.schema_common import _table_exists

    with connect() as conn:
        if not _table_exists(conn, "test_machines"):
            return []
        rows = conn.execute(
            "SELECT m.name, p.slug FROM test_machines m JOIN projects p "
            "ON p.id=m.power_project_id WHERE m.yoke_started_at IS NOT NULL"
        ).fetchall()
    return [
        {"power_project": project, "test_machine": name}
        for name, project in rows if name in hosts
    ]


def released_reset_debts(hosts: set[str]) -> list[dict[str, str]]:
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.machine_reset_debt import owed_reset
    from yoke_core.domain.schema_common import _table_exists

    with connect() as conn:
        if not _table_exists(conn, "test_machine_operation_receipts"):
            return []
        return [
            {"test_machine": host, "baseline": debt.baseline}
            for host in sorted(hosts)
            if (debt := owed_reset(conn, host)) is not None and debt.attempt is None
        ]


def released_hosts_response(response: Any, hosts: set[str]) -> Any:
    """Name any work still owed on the released hosts, or warn why it is unknown."""
    if not hosts:
        return response
    from yoke_contracts.api.function_call import FunctionWarning

    updates = {}
    warnings = list(response.warnings)
    for field, read, recovery in (
        ("test_machines_to_stop", released_cloud_machines,
         "a cloud host may stay running until its next lease ends"),
        ("test_machines_to_reset", released_reset_debts,
         "check the fleet report and run the owed reset from the credential-owning CLI"),
    ):
        try:
            updates[field] = read(hosts)
        except Exception as exc:  # noqa: BLE001 - the call's own result stands
            warnings.append(FunctionWarning(
                code="test_machine_release_notice_failed",
                step=field,
                detail=f"checking released hosts {sorted(hosts)} failed "
                f"({type(exc).__name__}); {recovery}",
            ))
    return response.model_copy(update={**updates, "warnings": warnings})


__all__ = [
    "collect_released_hosts",
    "released_hosts_response",
    "note_released_host",
    "released_cloud_machines",
]
