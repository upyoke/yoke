"""Tell the calling client which cloud Test Machines its call left unleased.

Starting and stopping a cloud Test Machine needs the project's aws-admin key,
which lives only on executing machines, so the control plane cannot stop a
host itself. Instead, every release of a host lease that leaves the host
free (no waiter's turn reserved) is noted during the call, and the response
names those hosts with ``cloud_instance_id``. Whichever client made the call,
whatever command it was, then stops them (``test_machine_power``). The note
is a hint: the client rechecks the lease under the host's own claim first.
"""

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

    if active_claim(conn, target) is None:
        hosts.add(str(target.test_machine))


def released_cloud_machines(hosts: set[str]) -> list[dict[str, str]]:
    """The released hosts that record ``cloud_instance_id``, by project."""
    if not hosts:
        return []
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.machine_qa_capability_rows import (
        test_machine_capability_rows,
    )

    with connect() as conn:
        rows = test_machine_capability_rows(conn)
    return [
        {"project": row.project, "test_machine": row.test_machine}
        for row in rows
        if row.test_machine in hosts and row.settings.get("cloud_instance_id")
    ]


def released_hosts_response(response: Any, hosts: set[str]) -> Any:
    """Name the call's freed cloud hosts on its response, or warn why not."""
    if not hosts:
        return response
    from yoke_contracts.api.function_call import FunctionWarning

    try:
        machines = released_cloud_machines(hosts)
    except Exception as exc:  # noqa: BLE001 - the call's own result stands
        warning = FunctionWarning(
            code="test_machine_release_notice_failed",
            step="released_test_machines",
            detail=f"released hosts {sorted(hosts)} were not checked for "
            f"cloud_instance_id ({type(exc).__name__}: {exc}); a cloud host "
            "among them stays running until its next lease ends",
        )
        return response.model_copy(
            update={"warnings": [*response.warnings, warning]}
        )
    if not machines:
        return response
    return response.model_copy(update={"released_test_machines": machines})


__all__ = [
    "collect_released_hosts",
    "released_hosts_response",
    "note_released_host",
    "released_cloud_machines",
]
