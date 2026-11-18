"""Read universe Test Machine identities and validated settings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError,
    validate_test_machine_resource_name,
    validate_test_machine_settings,
)
from yoke_contracts.timestamps import parse_instant

from yoke_core.domain.db_backend import connection_is_postgres


@dataclass(frozen=True)
class TestMachineRow:
    id: int
    power_project_id: int | None
    power_project: str | None
    test_machine: str
    settings: dict[str, str]
    settings_token: str
    verified_at: datetime | None
    created_at: datetime
    yoke_started: bool


def test_machine_rows(conn: Any) -> list[TestMachineRow]:
    rows = conn.execute(
        "SELECT m.id, m.power_project_id, p.slug, m.name, m.settings, "
        "m.verified_at, m.created_at, m.yoke_started_at FROM test_machines m "
        "LEFT JOIN projects p ON p.id=m.power_project_id ORDER BY m.name"
    ).fetchall()
    result = []
    for machine_id, project_id, project, name, token, verified_at, created_at, yoke_started_at in rows:
        try:
            name = validate_test_machine_resource_name(name)
            settings = validate_test_machine_settings(json.loads(token))
            if settings["resource_name"] != name:
                raise ValueError("resource_name must match the registered name")
        except (TypeError, ValueError) as exc:
            raise TestMachineCapabilityError(
                f"stored Test Machine {name!r} is invalid: {exc}; "
                "replace its settings with yoke test-machine settings-replace"
            ) from exc
        result.append(
            TestMachineRow(
                id=machine_id,
                power_project_id=project_id,
                power_project=project,
                test_machine=name,
                settings=settings,
                settings_token=token,
                verified_at=parse_instant(verified_at) if verified_at is not None else None,
                created_at=parse_instant(created_at),
                yoke_started=yoke_started_at is not None,
            )
        )
    return result


def select_test_machine_row(
    rows: list[TestMachineRow], *, test_machine: str | None
) -> TestMachineRow:
    if test_machine is not None:
        selected = validate_test_machine_resource_name(test_machine)
        for row in rows:
            if row.test_machine == selected:
                return row
        raise TestMachineCapabilityError(
            f"Test Machine {selected!r} is unregistered; run yoke test-machine list"
        )
    if len(rows) == 1:
        return rows[0]
    if not rows:
        raise TestMachineCapabilityError(
            "no Test Machines are registered; register one with yoke test-machine settings-replace"
        )
    available = ", ".join(row.test_machine for row in rows)
    raise TestMachineCapabilityError(
        f"multiple Test Machines are registered: {available}; pass --test-machine NAME"
    )


def test_machine_id(conn: Any, name: str) -> int:
    p = "%s" if connection_is_postgres(conn) else "?"
    row = conn.execute(f"SELECT id FROM test_machines WHERE name={p}", (name,)).fetchone()
    if row is None:
        raise TestMachineCapabilityError(
            f"Test Machine {name!r} is unregistered; run yoke test-machine list"
        )
    return int(row[0])
