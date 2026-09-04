"""Typed project capability model for one serially controlled test machine."""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.machine_config.capability_secrets import (
    TEST_MACHINE_CAPABILITY,
    TEST_MACHINE_SECRET_KEYS,
)
from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError,
    validate_test_machine_resource_name,
    validate_test_machine_settings,
)
from yoke_contracts.machine_config.test_machine import TEST_MACHINE_HOST_KINDS
from yoke_contracts.machine_qa_execution import (
    HOST_BASELINE_END_STATE,
    HOST_BASELINES,
)

from yoke_core.domain import db_backend
from yoke_core.domain.qa_method_capabilities import capability_kinds
from yoke_core.domain.capability_machine_secrets import (
    list_machine_capability_secret_keys,
)
from yoke_core.domain.capability_type_definitions import (
    capability_type_definition,
)
from yoke_core.domain.coordination_claim_keys import QA_HOST_KEY_PREFIX
from yoke_core.domain.coordination_claims import active_claim
from yoke_core.domain.machine_qa_capability_rows import (
    TestMachineCapabilityRow,
    select_test_machine_row,
    test_machine_capability_rows,
)
from yoke_core.domain.machine_operation_recording import (
    test_machine_operation_receipts,
)
from yoke_core.domain.machine_qa_capability_settings import (
    replace_test_machine_settings,
)
from yoke_core.domain.project_identity import (
    DEFAULT_PUBLIC_ITEM_PREFIX,
    render_item_ref,
    resolve_project,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.machine_verification_schema import ensure_test_machine_schema
from yoke_core.domain.work_claim_target_sql import scope_int_sql
from yoke_core.domain.work_claim_targets import make_qa_admission_target


HOST_CONTROL_EXECUTOR_ID = "host_control"
TEST_MACHINE_FEATURES = (
    "Terminal.app",
    "PTY",
    "screenshots",
    "post-install shell",
)
TEST_MACHINE_BASELINES = HOST_BASELINES


def validate_test_machine_json(raw_json: str) -> str:
    """Validate and deterministically encode a settings JSON object."""
    try:
        payload = json.loads(raw_json)
    except (TypeError, ValueError) as exc:
        raise TestMachineCapabilityError(
            "test-machine settings must be valid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise TestMachineCapabilityError("test-machine settings must be an object")
    return json.dumps(
        validate_test_machine_settings(payload),
        separators=(",", ":"),
        sort_keys=True,
    )


def host_claim_target(resource_name: str):
    """Return the exclusive coordination target for one physical host.

    A physical machine is globally unique, and so is its claim: the scope
    names the machine and nothing else, so whichever project drives a run
    contends for the same single row.
    """
    return make_qa_admission_target(validate_test_machine_resource_name(resource_name))


def host_claim_key(resource_name: str) -> str:
    """Render the operator-facing key addressing one physical host."""
    return QA_HOST_KEY_PREFIX + validate_test_machine_resource_name(resource_name)


def _holder_item(
    conn: Any,
    *,
    session_id: str,
) -> dict[str, Any] | None:
    """Return the work item whose execution owns a machine claim, if known."""
    if not all(_table_exists(conn, table) for table in ("work_claims", "items")):
        return None
    required_columns = {
        "work_claims": (
            "id",
            "session_id",
            "target_kind",
            "scope",
            "released_at",
            "claimed_at",
        ),
        "items": ("id", "title"),
    }
    if any(
        not _column_exists(conn, table, column)
        for table, columns in required_columns.items()
        for column in columns
    ):
        return None
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    item_id_scope = scope_int_sql(conn, "wc.scope", "item_id")
    row = conn.execute(
        f"SELECT {item_id_scope} AS item_id, i.title FROM work_claims wc "
        f"JOIN items i ON i.id={item_id_scope} "
        f"WHERE wc.session_id={marker} AND wc.target_kind='item' "
        "AND wc.released_at IS NULL "
        "ORDER BY wc.claimed_at DESC, wc.id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    item_id = int(row[0])
    ref = f"{DEFAULT_PUBLIC_ITEM_PREFIX}-{item_id}"
    if (
        _table_exists(conn, "projects")
        and all(
            _column_exists(conn, "items", column)
            for column in ("project_id", "project_sequence")
        )
        and all(
            _column_exists(conn, "projects", column)
            for column in ("id", "slug", "public_item_prefix")
        )
    ):
        ref = render_item_ref(conn, item_id)
    return {
        "id": item_id,
        "ref": ref,
        "title": str(row[1] or ""),
    }


def host_end_state(checks: list[dict[str, Any]]) -> str | None:
    """Say plainly what state a recorded run left the machine in.

    Verification reaches both baselines in order, so the box it hands back is
    whatever the LAST one it reached leaves behind -- which is not fresh. That
    sentence is derived from the rows rather than assumed, because a run that
    stopped early left the machine somewhere else entirely.
    """
    reached = [
        str(check["name"])
        for check in checks
        if check.get("ok") and str(check.get("name")) in HOST_BASELINE_END_STATE
    ]
    if not reached:
        return None
    return HOST_BASELINE_END_STATE[reached[-1]]


def _test_machine_detail(
    conn: Any,
    *,
    row: TestMachineCapabilityRow,
) -> dict[str, Any]:
    """Return the exact secret-free projection needed by the Test Mac screen."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    verification = conn.execute(
        "SELECT status,checked_at,receipt_json,error_code "
        "FROM test_machine_verifications "
        f"WHERE project_id={marker} AND capability_type={marker}",
        (row.project_id, row.capability_type),
    ).fetchone()
    receipt = json.loads(str(verification[2] or "{}")) if verification else {}
    resource_name = row.settings["resource_name"]
    claim = active_claim(conn, host_claim_target(resource_name))
    claim_item = (
        _holder_item(conn, session_id=claim.session_id) if claim is not None else None
    )
    methods = [
        method
        for method in conn.execute(
            "SELECT id,name,source_ref,required_capability_kinds "
            "FROM qa_methods ORDER BY name"
        ).fetchall()
        if TEST_MACHINE_CAPABILITY
        in capability_kinds(
            method[3],
            subject=f"method {method[0]!r}",
        )
    ]
    stored_keys = set(
        list_machine_capability_secret_keys(row.project, TEST_MACHINE_CAPABILITY)
    )
    status = (
        str(verification[0])
        if verification is not None
        else ("verified" if row.verified_at else "configured_unverified")
    )
    definition = capability_type_definition(row.capability_type)
    return {
        "project_id": row.project_id,
        "project": row.project,
        "machine": row.machine,
        "capability_type": row.capability_type,
        "kind": TEST_MACHINE_CAPABILITY,
        "display_name": definition["display_label"],
        "runner_id": HOST_CONTROL_EXECUTOR_ID,
        "settings": row.settings,
        "settings_token": row.settings_token,
        "features": list(TEST_MACHINE_FEATURES),
        "host_baselines": list(TEST_MACHINE_BASELINES),
        "host_baseline_end_states": dict(HOST_BASELINE_END_STATE),
        "host_kinds": list(TEST_MACHINE_HOST_KINDS),
        "concurrency": {"limit": 1, "mode": "serial", "scope": "machine"},
        "verification": {
            "status": status,
            "checked_at": verification[1] if verification else row.verified_at,
            "error_code": verification[3] if verification else None,
            "checks": list(receipt.get("checks") or []),
            "host_end_state": host_end_state(list(receipt.get("checks") or [])),
        },
        "operations": test_machine_operation_receipts(
            conn,
            row.project_id,
            capability_type=row.capability_type,
        ),
        "secrets": [
            {"key": key, "stored": key in stored_keys}
            for key in sorted(TEST_MACHINE_SECRET_KEYS)
        ],
        "active_lease": (
            {
                "id": claim.id,
                "session_id": claim.session_id,
                "actor_id": claim.actor_id,
                "acquired_at": claim.claimed_at,
                "heartbeat_at": claim.last_heartbeat,
                "item": claim_item,
            }
            if claim is not None
            else None
        ),
        "methods": [
            {"id": str(row[0]), "name": str(row[1]), "source_ref": row[2]}
            for row in methods
        ],
    }


def test_machine_detail(
    conn: Any,
    *,
    project: str,
    machine: str | None = None,
) -> dict[str, Any]:
    """Return one selected machine, allowing omission only for one-row fleets."""
    identity = resolve_project(conn, project, required=False)
    if identity is None:
        raise TestMachineCapabilityError(f"project {project!r} not found")
    ensure_test_machine_schema(conn)
    rows = test_machine_capability_rows(conn, project_id=identity.id)
    selected = select_test_machine_row(
        rows,
        project=identity.slug,
        machine=machine,
    )
    return _test_machine_detail(conn, row=selected)


def test_machine_list(conn: Any, *, project: str) -> dict[str, Any]:
    """Return every independently readable machine registered by a project."""
    identity = resolve_project(conn, project, required=False)
    if identity is None:
        raise TestMachineCapabilityError(f"project {project!r} not found")
    ensure_test_machine_schema(conn)
    rows = test_machine_capability_rows(conn, project_id=identity.id)
    return {
        "project_id": int(identity.id),
        "project": identity.slug,
        "machines": [_test_machine_detail(conn, row=row) for row in rows],
    }


__all__ = [
    "HOST_CONTROL_EXECUTOR_ID",
    "host_end_state",
    "TEST_MACHINE_BASELINES",
    "TEST_MACHINE_FEATURES",
    "TestMachineCapabilityError",
    "host_claim_key",
    "host_claim_target",
    "replace_test_machine_settings",
    "test_machine_detail",
    "test_machine_list",
    "validate_test_machine_json",
    "validate_test_machine_settings",
]
