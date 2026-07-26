"""Typed project capability model for one serially controlled test machine."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from yoke_contracts.machine_config.capability_secrets import (
    TEST_MACHINE_CAPABILITY,
    TEST_MACHINE_SECRET_KEYS,
)

from yoke_core.domain import db_backend
from yoke_core.domain.capability_machine_secrets import (
    list_machine_capability_secret_keys,
)
from yoke_core.domain.coordination_leases import active_lease
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.test_machine_schema import ensure_test_machine_schema


HOST_CONTROL_EXECUTOR_ID = "host_control"
TEST_MACHINE_FEATURES = (
    "Terminal.app",
    "PTY",
    "screenshots",
    "post-install shell",
)
TEST_MACHINE_BASELINES = ("fresh-host", "shell-preconfigured")
_LEASE_PREFIX = "QA_HOST:"
_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_USER = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,63}$")
_SETTING_KEYS = frozenset({"resource_name", "host", "user", "operating_notes"})


class TestMachineCapabilityError(ValueError):
    """The test-machine declaration or update is invalid."""


def validate_test_machine_settings(payload: Mapping[str, Any]) -> dict[str, str]:
    """Return the canonical, non-secret settings document."""
    if set(payload) != _SETTING_KEYS:
        missing = sorted(_SETTING_KEYS - set(payload))
        unknown = sorted(set(payload) - _SETTING_KEYS)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if unknown:
            detail.append("unknown " + ", ".join(unknown))
        raise TestMachineCapabilityError(
            "test-machine settings require exactly resource_name, host, user, "
            "and operating_notes (" + "; ".join(detail) + ")"
        )
    values = {key: str(payload[key] or "").strip() for key in _SETTING_KEYS}
    if not _SLUG.fullmatch(values["resource_name"]):
        raise TestMachineCapabilityError("resource_name is not a safe resource label")
    host = values["host"]
    if not host or len(host) > 253 or any(ch.isspace() for ch in host):
        raise TestMachineCapabilityError("host must be a non-empty host name")
    if not _USER.fullmatch(values["user"]):
        raise TestMachineCapabilityError("user is not a safe remote user name")
    if len(values["operating_notes"]) > 500:
        raise TestMachineCapabilityError("operating_notes must be at most 500 characters")
    return {key: values[key] for key in sorted(values)}


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
    if not _SLUG.fullmatch(str(resource_name or "")):
        raise TestMachineCapabilityError("resource_name is not a safe resource label")
    return _LEASE_PREFIX + str(resource_name)


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
    canonical = json.dumps(
        validate_test_machine_settings(settings),
        separators=(",", ":"),
        sort_keys=True,
    )
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
    lease = active_lease(conn, identity.id, lease_key(settings["resource_name"]))
    methods = conn.execute(
        "SELECT id,name,source_ref FROM qa_methods "
        f"WHERE required_capability_kind={marker} ORDER BY name",
        (TEST_MACHINE_CAPABILITY,),
    ).fetchall()
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
        "display_name": "Test Mac",
        "executor_id": HOST_CONTROL_EXECUTOR_ID,
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
            }
            if lease is not None else None
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
