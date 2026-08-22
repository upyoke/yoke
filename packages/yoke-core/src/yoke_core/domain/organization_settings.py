"""Organization-wide settings reads and transactional merges."""

from __future__ import annotations

import json
from typing import Any, Mapping

from yoke_contracts.organization_contract.fleet_keys import (
    get_fleet_setting,
    merge_fleet_settings,
    validate_fleet_settings,
)
from yoke_core.domain import db_backend


class OrganizationSettingsError(ValueError):
    """The organization or its stored settings document is invalid."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _parse(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(str(raw or "{}"))
    except (TypeError, ValueError) as exc:
        raise OrganizationSettingsError(
            "stored organization settings are not valid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise OrganizationSettingsError(
            "stored organization settings must be a JSON object"
        )
    validate_fleet_settings(value)
    return value


def read_organization_settings(conn: Any, org_id: int) -> dict[str, Any]:
    marker = _p(conn)
    row = conn.execute(
        f"SELECT settings FROM organizations WHERE id={marker}",
        (int(org_id),),
    ).fetchone()
    if row is None:
        raise OrganizationSettingsError(f"organization {org_id} does not exist")
    return _parse(row[0])


def read_organization_setting(
    conn: Any,
    org_id: int,
    path: str,
) -> tuple[Any, bool]:
    """Return one scalar registry leaf and whether its default supplied it."""
    value, defaulted = get_fleet_setting(
        read_organization_settings(conn, org_id),
        path,
    )
    if isinstance(value, (dict, list)):
        raise OrganizationSettingsError(
            f"organization setting {path!r} is not a scalar leaf"
        )
    return value, defaulted


def merge_organization_settings(
    conn: Any,
    org_id: int,
    changes: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Lock, validate, merge, and store explicit organization overrides."""
    marker = _p(conn)
    suffix = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    row = conn.execute(
        f"SELECT settings FROM organizations WHERE id={marker}{suffix}",
        (int(org_id),),
    ).fetchone()
    if row is None:
        raise OrganizationSettingsError(f"organization {org_id} does not exist")
    merged, changed_paths = merge_fleet_settings(_parse(row[0]), changes)
    if not changed_paths:
        raise OrganizationSettingsError(
            "at least one organization setting assignment is required"
        )
    conn.execute(
        f"UPDATE organizations SET settings={marker} WHERE id={marker}",
        (json.dumps(merged, sort_keys=True), int(org_id)),
    )
    conn.commit()
    return merged, changed_paths


__all__ = [
    "OrganizationSettingsError",
    "merge_organization_settings",
    "read_organization_setting",
    "read_organization_settings",
]
