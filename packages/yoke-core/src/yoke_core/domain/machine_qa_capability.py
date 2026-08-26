"""Typed project capability model for one serially controlled test machine."""

from __future__ import annotations

import json
from typing import Any, Mapping

from yoke_contracts.machine_config.capability_secrets import (
    TEST_MACHINE_CAPABILITY,
    TEST_MACHINE_SECRET_KEYS,
)
from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError,
    validate_test_machine_resource_name,
    validate_test_machine_settings,
)
from yoke_contracts.machine_qa_execution import VERIFICATION_BASELINES

from yoke_core.domain import db_backend
from yoke_core.domain.qa_method_capabilities import capability_kinds
from yoke_core.domain.capability_machine_secrets import (
    list_machine_capability_secret_keys,
)
from yoke_core.domain.capability_type_definitions import (
    capability_type_definition,
)
from yoke_core.domain.coordination_leases import active_lease
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.machine_qa_host_registrar import (
    assert_sole_host_registrar,
    host_lease_project_id,
)
from yoke_core.domain.project_identity import (
    DEFAULT_PUBLIC_ITEM_PREFIX,
    render_item_ref,
    resolve_project,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.machine_verification_schema import ensure_test_machine_schema
from yoke_core.domain.work_claim_targets import scope_int_sql


HOST_CONTROL_EXECUTOR_ID = "host_control"
TEST_MACHINE_FEATURES = (
    "Terminal.app",
    "PTY",
    "screenshots",
    "post-install shell",
)
TEST_MACHINE_BASELINES = VERIFICATION_BASELINES
_LEASE_PREFIX = "QA_HOST:"


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


def lease_key(resource_name: str) -> str:
    """Exclusive coordination key for one physical test resource."""
    return _LEASE_PREFIX + validate_test_machine_resource_name(resource_name)


def _lease_item(
    conn: Any,
    *,
    session_id: str,
) -> dict[str, Any] | None:
    """Return the work item whose execution owns a machine lease, if known."""
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


def replace_test_machine_settings(
    conn: Any,
    *,
    project: str,
    settings: Mapping[str, Any],
    base_settings: str | None,
) -> dict[str, Any]:
    """CAS-replace settings and invalidate every prior verification receipt."""
    identity = resolve_project(conn, project, required=False)
    if identity is None:
        raise TestMachineCapabilityError(f"project {project!r} not found")
    ensure_test_machine_schema(conn)
    document = validate_test_machine_settings(settings)
    assert_sole_host_registrar(
        conn,
        project_id=identity.id,
        resource_name=document["resource_name"],
    )
    canonical = json.dumps(document, separators=(",", ":"), sort_keys=True)
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT COALESCE(settings, '{}') FROM project_capabilities "
        f"WHERE project_id={marker} AND type={marker}",
        (identity.id, TEST_MACHINE_CAPABILITY),
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
            (
                identity.id,
                TEST_MACHINE_CAPABILITY,
                canonical,
                iso8601_now(),
            ),
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
            (canonical, identity.id, TEST_MACHINE_CAPABILITY),
        )
    now = iso8601_now()
    conn.execute(
        "INSERT INTO test_machine_verifications("
        "project_id,status,checked_at,receipt_json,error_code,updated_at"
        f") VALUES({marker},'configured_unverified',NULL,'{{}}',NULL,{marker}) "
        "ON CONFLICT(project_id) DO UPDATE SET "
        "status='configured_unverified', checked_at=NULL, receipt_json='{}', "
        "error_code=NULL, updated_at=EXCLUDED.updated_at",
        (identity.id, now),
    )
    conn.commit()
    return {
        "project_id": int(identity.id),
        "project": identity.slug,
        "settings": json.loads(canonical),
        "settings_token": canonical,
        "verification_status": "configured_unverified",
    }


def test_machine_detail(conn: Any, *, project: str) -> dict[str, Any]:
    """Return the exact secret-free projection needed by the Test Mac screen."""
    identity = resolve_project(conn, project, required=False)
    if identity is None:
        raise TestMachineCapabilityError(f"project {project!r} not found")
    ensure_test_machine_schema(conn)
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT COALESCE(settings, '{}'), verified_at "
        "FROM project_capabilities "
        f"WHERE project_id={marker} AND type={marker}",
        (identity.id, TEST_MACHINE_CAPABILITY),
    ).fetchone()
    if row is None:
        raise TestMachineCapabilityError(
            f"project {identity.slug!r} has no test-machine capability"
        )
    settings_token = str(row[0])
    settings = validate_test_machine_settings(json.loads(settings_token))
    verification = conn.execute(
        "SELECT status,checked_at,receipt_json,error_code "
        f"FROM test_machine_verifications WHERE project_id={marker}",
        (identity.id,),
    ).fetchone()
    receipt = json.loads(str(verification[2] or "{}")) if verification else {}
    resource_name = settings["resource_name"]
    lease = active_lease(
        conn,
        host_lease_project_id(conn, resource_name),
        lease_key(resource_name),
    )
    lease_item = (
        _lease_item(conn, session_id=lease.session_id) if lease is not None else None
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
        list_machine_capability_secret_keys(identity.slug, TEST_MACHINE_CAPABILITY)
    )
    status = (
        str(verification[0])
        if verification is not None
        else ("verified" if row[1] else "configured_unverified")
    )
    return {
        "project_id": int(identity.id),
        "project": identity.slug,
        "kind": TEST_MACHINE_CAPABILITY,
        "display_name": capability_type_definition(TEST_MACHINE_CAPABILITY)[
            "display_label"
        ],
        "runner_id": HOST_CONTROL_EXECUTOR_ID,
        "settings": settings,
        "settings_token": settings_token,
        "features": list(TEST_MACHINE_FEATURES),
        "host_baselines": list(TEST_MACHINE_BASELINES),
        "concurrency": {"limit": 1, "mode": "serial"},
        "verification": {
            "status": status,
            "checked_at": verification[1] if verification else row[1],
            "error_code": verification[3] if verification else None,
            "checks": list(receipt.get("checks") or []),
        },
        "secrets": [
            {"key": key, "stored": key in stored_keys}
            for key in sorted(TEST_MACHINE_SECRET_KEYS)
        ],
        "active_lease": (
            {
                "id": lease.id,
                "session_id": lease.session_id,
                "actor_id": lease.actor_id,
                "acquired_at": lease.acquired_at,
                "heartbeat_at": lease.heartbeat_at,
                "item": lease_item,
            }
            if lease is not None
            else None
        ),
        "methods": [
            {"id": str(row[0]), "name": str(row[1]), "source_ref": row[2]}
            for row in methods
        ],
    }


__all__ = [
    "HOST_CONTROL_EXECUTOR_ID",
    "TEST_MACHINE_BASELINES",
    "TEST_MACHINE_FEATURES",
    "TestMachineCapabilityError",
    "lease_key",
    "replace_test_machine_settings",
    "test_machine_detail",
    "validate_test_machine_json",
    "validate_test_machine_settings",
]
