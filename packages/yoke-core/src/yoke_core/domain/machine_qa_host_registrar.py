"""Project authority for one physical QA host shared across projects.

A physical test machine is a globally unique resource, and its coordination
claim says so: the claim scope names the machine alone, so one host sits
behind one row no matter which project drives the run. What still needs
declaring is who operates the machine, which is what the registration guard
below keeps unique.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from yoke_contracts.machine_config.test_machine import (
    TEST_MACHINE_CAPABILITY_PREFIX,
    TestMachineCapabilityError,
    test_machine_resource_name,
    validate_test_machine_resource_name,
)

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists


@dataclass(frozen=True)
class HostRegistration:
    """One project's declaration that it operates a named physical host."""

    project_id: int
    project: str
    capability_type: str
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
        "SELECT c.project_id, COALESCE(p.slug, ''), c.type, "
        "COALESCE(c.settings, '{}') "
        "FROM project_capabilities c "
        "LEFT JOIN projects p ON p.id = c.project_id "
        f"WHERE c.type LIKE {marker} "
        "ORDER BY c.created_at, c.project_id, c.type",
        (TEST_MACHINE_CAPABILITY_PREFIX + "%",),
    ).fetchall()
    registrations: list[HostRegistration] = []
    for row in rows:
        try:
            capability_type = str(row[2])
            type_machine = test_machine_resource_name(capability_type)
            settings = json.loads(str(row[3]))
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
        if resource_name != type_machine:
            continue
        registrations.append(
            HostRegistration(
                project_id=int(row[0]),
                project=str(row[1]),
                capability_type=capability_type,
                resource_name=resource_name,
            )
        )
    return registrations


def assert_sole_host_registrar(
    conn: Any,
    *,
    project_id: int,
    capability_type: str,
    resource_name: str,
) -> None:
    """Refuse a second declaration for one globally unique physical host."""
    canonical = validate_test_machine_resource_name(resource_name)
    for registration in host_registrations(conn):
        if registration.resource_name != canonical:
            continue
        if (
            registration.project_id == int(project_id)
            and registration.capability_type == capability_type
        ):
            continue
        if registration.project_id != int(project_id):
            owner = registration.project or str(registration.project_id)
            raise TestMachineCapabilityError(
                f"test machine {canonical!r} is already registered by project "
                f"{owner!r}; one physical host belongs to exactly one project"
            )
        raise TestMachineCapabilityError(
            f"project {registration.project!r} already registers test machine "
            f"{canonical!r} as {registration.capability_type!r}; one physical "
            "host cannot occupy two capability rows"
        )


__all__ = [
    "HostRegistration",
    "assert_sole_host_registrar",
    "host_registrations",
]
