"""Validated storage rows for independently registered QA machines."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from yoke_contracts.machine_config.test_machine import (
    TEST_MACHINE_CAPABILITY_PREFIX,
    TestMachineCapabilityError,
    test_machine_capability_type,
    test_machine_resource_name,
    validate_test_machine_resource_name,
    validate_test_machine_settings,
)

from yoke_core.domain import db_backend


@dataclass(frozen=True)
class TestMachineCapabilityRow:
    """One canonical project capability row and its validated settings."""

    project_id: int
    project: str
    capability_type: str
    machine: str
    settings: dict[str, str]
    settings_token: str
    verified_at: str | None
    created_at: str


def test_machine_capability_rows(
    conn: Any,
    *,
    project_id: int | None = None,
) -> list[TestMachineCapabilityRow]:
    """Return canonical machine rows, refusing corrupt identity pairs."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    where = f"AND c.project_id={marker}" if project_id is not None else ""
    params: tuple[Any, ...] = (
        TEST_MACHINE_CAPABILITY_PREFIX + "%",
        *((int(project_id),) if project_id is not None else ()),
    )
    rows = conn.execute(
        "SELECT c.project_id,COALESCE(p.slug,''),c.type,"
        "COALESCE(c.settings,'{}'),c.verified_at,c.created_at "
        "FROM project_capabilities c "
        "LEFT JOIN projects p ON p.id=c.project_id "
        f"WHERE c.type LIKE {marker} {where} "
        "ORDER BY c.project_id,c.type",
        params,
    ).fetchall()
    result: list[TestMachineCapabilityRow] = []
    for raw in rows:
        capability_type = str(raw[2])
        try:
            machine = test_machine_resource_name(capability_type)
            settings_token = str(raw[3])
            settings = validate_test_machine_settings(json.loads(settings_token))
        except (TypeError, ValueError, TestMachineCapabilityError) as exc:
            raise TestMachineCapabilityError(
                f"stored capability {capability_type!r} is invalid; replace its "
                "settings through yoke test-machine settings-replace"
            ) from exc
        if settings["resource_name"] != machine:
            raise TestMachineCapabilityError(
                f"stored capability {capability_type!r} names resource "
                f"{settings['resource_name']!r}; make the type suffix and "
                "resource_name identical"
            )
        result.append(
            TestMachineCapabilityRow(
                project_id=int(raw[0]),
                project=str(raw[1]),
                capability_type=capability_type,
                machine=machine,
                settings=settings,
                settings_token=settings_token,
                verified_at=(str(raw[4]) if raw[4] is not None else None),
                created_at=str(raw[5]),
            )
        )
    return result


def select_test_machine_row(
    rows: list[TestMachineCapabilityRow],
    *,
    project: str,
    machine: str | None,
) -> TestMachineCapabilityRow:
    """Select one row or teach the caller to make an ambiguous choice."""
    if machine is not None:
        selected = validate_test_machine_resource_name(machine)
        capability_type = test_machine_capability_type(selected)
        for row in rows:
            if row.capability_type == capability_type:
                return row
        available = ", ".join(row.machine for row in rows) or "none"
        raise TestMachineCapabilityError(
            f"project {project!r} has no test machine {selected!r}; "
            f"registered machines: {available}"
        )
    if not rows:
        raise TestMachineCapabilityError(
            f"project {project!r} has no test-machine capability"
        )
    if len(rows) > 1:
        available = ", ".join(row.machine for row in rows)
        raise TestMachineCapabilityError(
            f"project {project!r} has multiple test machines: {available}; "
            "pass --machine NAME"
        )
    return rows[0]


__all__ = [
    "TestMachineCapabilityRow",
    "select_test_machine_row",
    "test_machine_capability_rows",
]
