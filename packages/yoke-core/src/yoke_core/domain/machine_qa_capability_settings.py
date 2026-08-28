"""CAS mutation for one independently stored test-machine capability."""

from __future__ import annotations

import json
from typing import Any, Mapping

from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError,
    test_machine_capability_type,
    validate_test_machine_resource_name,
    validate_test_machine_settings,
)

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.machine_qa_capability_rows import (
    test_machine_capability_rows,
)
from yoke_core.domain.machine_qa_host_registrar import (
    assert_sole_host_registrar,
)
from yoke_core.domain.machine_verification_schema import ensure_test_machine_schema
from yoke_core.domain.project_identity import resolve_project


def _target_type(
    rows: list[Any],
    *,
    project: str,
    machine: str | None = None,
    document: Mapping[str, str],
) -> str:
    settings_machine = document["resource_name"]
    if machine is not None:
        selected = validate_test_machine_resource_name(machine)
        if selected != settings_machine:
            raise TestMachineCapabilityError(
                f"--machine {selected!r} does not match settings resource_name "
                f"{settings_machine!r}"
            )
        return test_machine_capability_type(selected)
    if len(rows) > 1:
        available = ", ".join(row.machine for row in rows)
        raise TestMachineCapabilityError(
            f"project {project!r} has multiple test machines: {available}; "
            "pass --machine NAME"
        )
    if rows and rows[0].machine != settings_machine:
        raise TestMachineCapabilityError(
            f"settings name test machine {settings_machine!r}, but the project has "
            f"one machine {rows[0].machine!r}; pass --machine "
            f"{settings_machine} --new to register another machine"
        )
    return test_machine_capability_type(settings_machine)


def replace_test_machine_settings(
    conn: Any,
    *,
    project: str,
    settings: Mapping[str, Any],
    base_settings: str | None,
    machine: str | None = None,
) -> dict[str, Any]:
    """CAS-replace one machine row and invalidate only its verification."""
    identity = resolve_project(conn, project, required=False)
    if identity is None:
        raise TestMachineCapabilityError(f"project {project!r} not found")
    ensure_test_machine_schema(conn)
    document = validate_test_machine_settings(settings)
    rows = test_machine_capability_rows(conn, project_id=identity.id)
    capability_type = _target_type(
        rows,
        project=identity.slug,
        machine=machine,
        document=document,
    )
    assert_sole_host_registrar(
        conn,
        project_id=identity.id,
        capability_type=capability_type,
        resource_name=document["resource_name"],
    )
    canonical = json.dumps(document, separators=(",", ":"), sort_keys=True)
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT COALESCE(settings, '{}') FROM project_capabilities "
        f"WHERE project_id={marker} AND type={marker}",
        (identity.id, capability_type),
    ).fetchone()
    if row is None:
        if base_settings is not None:
            raise TestMachineCapabilityError(
                "test-machine settings changed; reload before saving"
            )
        conn.execute(
            "INSERT INTO project_capabilities("
            "project_id,type,settings,verified_at,created_at"
            f") VALUES({marker},{marker},{marker},NULL,{marker})",
            (identity.id, capability_type, canonical, iso8601_now()),
        )
    else:
        stored = str(row[0])
        if base_settings is None or stored != base_settings:
            raise TestMachineCapabilityError(
                "test-machine settings changed; reload before saving"
            )
        conn.execute(
            "UPDATE project_capabilities SET settings="
            f"{marker}, verified_at=NULL WHERE project_id={marker} AND type={marker}",
            (canonical, identity.id, capability_type),
        )
    now = iso8601_now()
    conn.execute(
        "INSERT INTO test_machine_verifications("
        "project_id,capability_type,status,checked_at,receipt_json,error_code,updated_at"
        f") VALUES({marker},{marker},'configured_unverified',NULL,'{{}}',NULL,{marker}) "
        "ON CONFLICT(project_id,capability_type) DO UPDATE SET "
        "status='configured_unverified', checked_at=NULL, receipt_json='{}', "
        "error_code=NULL, updated_at=EXCLUDED.updated_at",
        (identity.id, capability_type, now),
    )
    conn.commit()
    return {
        "project_id": int(identity.id),
        "project": identity.slug,
        "machine": document["resource_name"],
        "capability_type": capability_type,
        "settings": json.loads(canonical),
        "settings_token": canonical,
        "verification_status": "configured_unverified",
    }


__all__ = ["replace_test_machine_settings"]
