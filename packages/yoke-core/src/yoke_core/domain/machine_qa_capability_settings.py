"""Compare and replace settings for one Test Machine."""

from __future__ import annotations

import json
from typing import Any, Mapping

from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError,
    validate_test_machine_resource_name,
    validate_test_machine_settings,
)

from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.db_helpers import instant_parameter, utc_now
from yoke_core.domain.project_identity import resolve_project


def replace_test_machine_settings(
    conn: Any,
    *,
    power_project: str | None = None,
    settings: Mapping[str, Any],
    base_settings: str | None,
    test_machine: str | None = None,
    caller_session_id: str | None = None,
) -> dict[str, Any]:
    """CAS-replace one machine row and invalidate only its verification.

    A live lease blocks the change unless the caller's own session holds it:
    the lease holder is the one session that can change its host safely.
    """
    document = validate_test_machine_settings(settings)
    name = document["resource_name"]
    if test_machine is not None and validate_test_machine_resource_name(test_machine) != name:
        raise TestMachineCapabilityError(
            f"--test-machine {test_machine!r} does not match settings resource_name {name!r}"
        )

    project = None
    if power_project is not None:
        project = resolve_project(conn, power_project, required=False)
        if project is None:
            raise TestMachineCapabilityError(
                f"power project {power_project!r} not found; run yoke projects list"
            )

    canonical = json.dumps(document, separators=(",", ":"), sort_keys=True)
    p = "%s" if connection_is_postgres(conn) else "?"
    from yoke_core.domain.coordination_claims import active_claim
    from yoke_core.domain.qa_host_turns import lock_host_turn
    from yoke_core.domain.schema_common import _table_exists
    from yoke_core.domain.work_claim_targets import make_qa_admission_target

    target = make_qa_admission_target(name)
    lock_host_turn(conn, target)
    holder = active_claim(conn, target) if _table_exists(conn, "work_claims") else None
    if holder is not None and (
        caller_session_id is None or holder.session_id != caller_session_id
    ):
        raise TestMachineCapabilityError(
            f"{name} is leased by session {holder.session_id}; retry after its lease "
            "is released, or change the settings from the session holding the lease"
        )
    if base_settings is not None:
        existing = conn.execute(
            f"SELECT settings, power_project_id, yoke_started_at FROM test_machines WHERE name={p}",
            (name,),
        ).fetchone()
        if existing is not None and existing[2] is not None:
            old_settings = json.loads(existing[0])
            same_instance = all(
                old_settings.get(key) == document.get(key)
                for key in ("cloud_instance_id", "cloud_provider")
            )
            if not same_instance or (project is not None and project.id != existing[1]):
                raise TestMachineCapabilityError(
                    f"{name} has a pending Yoke power stop; let its lease cycle "
                    "complete and confirm the stop before changing the cloud registration"
                )
    now = instant_parameter(conn, utc_now())
    if base_settings is None:
        if document.get("cloud_instance_id") and project is None:
            raise TestMachineCapabilityError(
                "a cloud Test Machine requires a power project; pass --power-project PROJECT"
            )
        saved = conn.execute(
            "INSERT INTO test_machines (name, settings, power_project_id, created_at) "
            f"VALUES ({p}, {p}, {p}, {p}) ON CONFLICT(name) DO NOTHING "
            "RETURNING id, power_project_id",
            (name, canonical, project.id if project else None, now),
        ).fetchone()
    else:
        saved = conn.execute(
            f"UPDATE test_machines SET settings={p}, verified_at=NULL, "
            f"power_project_id=COALESCE({p}, power_project_id) "
            f"WHERE name={p} AND settings={p} RETURNING id, power_project_id",
            (canonical, project.id if project else None, name, base_settings),
        ).fetchone()
    if saved is None:
        raise TestMachineCapabilityError(
            "test-machine settings changed; reload before saving"
        )
    machine_id, owner_id = saved
    if document.get("cloud_instance_id") and owner_id is None:
        raise TestMachineCapabilityError(
            "a cloud Test Machine requires a power project; pass --power-project PROJECT"
        )
    owner = conn.execute(f"SELECT slug FROM projects WHERE id={p}", (owner_id,)).fetchone()
    conn.execute(
        "INSERT INTO test_machine_verifications (test_machine_id,status,updated_at) "
        f"VALUES ({p}, 'configured_unverified', {p}) "
        "ON CONFLICT(test_machine_id) DO UPDATE SET "
        "status='configured_unverified', checked_at=NULL, receipt_json='{}', "
        "error_code=NULL, updated_at=EXCLUDED.updated_at",
        (machine_id, now),
    )
    conn.commit()
    return {
        "id": machine_id,
        "power_project_id": owner_id,
        "power_project": owner[0] if owner else None,
        "test_machine": name,
        "settings": document,
        "settings_token": canonical,
        "verification_status": "configured_unverified",
    }
