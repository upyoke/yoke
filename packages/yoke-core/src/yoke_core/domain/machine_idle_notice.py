"""Return idle Test Machines whose power marker calls for a client-side stop."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_released: ContextVar[set[str] | None] = ContextVar(
    "test_machines_to_stop", default=None
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
    from yoke_core.domain.db_backend import connection_is_postgres
    from yoke_core.domain.schema_common import _table_exists

    if not _table_exists(conn, "test_machines"):
        return
    p = "%s" if connection_is_postgres(conn) else "?"
    marked = conn.execute(
        f"SELECT 1 FROM test_machines WHERE name={p} AND yoke_started_at IS NOT NULL",
        (target.test_machine,),
    ).fetchone()
    if marked:
        hosts.add(str(target.test_machine))


def released_cloud_machines(hosts: set[str]) -> list[dict[str, str]]:
    """The released hosts that record ``cloud_instance_id``, by project."""
    if not hosts:
        return []
    from yoke_core.domain.db_helpers import connect
    with connect() as conn:
        rows = conn.execute(
            "SELECT m.name, p.slug FROM test_machines m JOIN projects p "
            "ON p.id=m.power_project_id WHERE m.yoke_started_at IS NOT NULL"
        ).fetchall()
    return [
        {"power_project": project, "test_machine": name}
        for name, project in rows if name in hosts
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
            step="test_machines_to_stop",
            detail=f"released hosts {sorted(hosts)} were not checked for "
            f"cloud_instance_id ({type(exc).__name__}: {exc}); a cloud host "
            "among them stays running until its next lease ends",
        )
        return response.model_copy(update={"warnings": [*response.warnings, warning]})
    if not machines:
        return response
    return response.model_copy(update={"test_machines_to_stop": machines})


__all__ = [
    "collect_released_hosts",
    "released_hosts_response",
    "note_released_host",
    "released_cloud_machines",
]
