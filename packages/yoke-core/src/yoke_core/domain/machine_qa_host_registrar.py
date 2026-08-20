"""Project authority for one physical QA host shared across projects.

A physical test machine is a globally unique resource, but a coordination
lease is unique per ``(project_id, lease_key)``. Anchoring every host lease
to the project that registered the machine keeps one physical host behind
one lease row no matter which project drives the run, and the registration
guard below keeps that registrar unique so the anchor stays well defined.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from yoke_contracts.machine_config.capability_secrets import (
    TEST_MACHINE_CAPABILITY,
)
from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError,
    validate_test_machine_resource_name,
)

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists


@dataclass(frozen=True)
class HostRegistration:
    """One project's declaration that it operates a named physical host."""

    project_id: int
    project: str
    resource_name: str


def host_registrations(conn: Any) -> list[HostRegistration]:
    """Return every registered physical host, oldest registration first.

    Settings that no longer parse or no longer name a usable resource are
    skipped so one damaged row cannot fail an unrelated project's read.
    """
    if not _table_exists(conn, "project_capabilities"):
        return []
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT c.project_id, COALESCE(p.slug, ''), COALESCE(c.settings, '{}') "
        "FROM project_capabilities c "
        "LEFT JOIN projects p ON p.id = c.project_id "
        f"WHERE c.type = {marker} "
        "ORDER BY c.created_at, c.project_id",
        (TEST_MACHINE_CAPABILITY,),
    ).fetchall()
    registrations: list[HostRegistration] = []
    for row in rows:
        try:
            settings = json.loads(str(row[2]))
        except ValueError:
            continue
        if not isinstance(settings, dict):
            continue
        try:
            resource_name = validate_test_machine_resource_name(
                settings.get("resource_name"),
            )
        except TestMachineCapabilityError:
            continue
        registrations.append(
            HostRegistration(
                project_id=int(row[0]),
                project=str(row[1]),
                resource_name=resource_name,
            )
        )
    return registrations


def host_lease_project_id(conn: Any, resource_name: str) -> int:
    """Return the project whose lease row serializes this physical host."""
    canonical = validate_test_machine_resource_name(resource_name)
    for registration in host_registrations(conn):
        if registration.resource_name == canonical:
            return registration.project_id
    raise TestMachineCapabilityError(
        f"test machine {canonical!r} is not registered by any project"
    )


def assert_sole_host_registrar(
    conn: Any,
    *,
    project_id: int,
    resource_name: str,
) -> None:
    """Refuse a registration for a host another project already operates."""
    canonical = validate_test_machine_resource_name(resource_name)
    for registration in host_registrations(conn):
        if registration.resource_name != canonical:
            continue
        if registration.project_id != int(project_id):
            owner = registration.project or str(registration.project_id)
            raise TestMachineCapabilityError(
                f"test machine {canonical!r} is already registered by project "
                f"{owner!r}; one physical host belongs to exactly one project"
            )


__all__ = [
    "HostRegistration",
    "assert_sole_host_registrar",
    "host_lease_project_id",
    "host_registrations",
]
